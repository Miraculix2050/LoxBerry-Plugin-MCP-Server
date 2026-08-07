#!/usr/bin/env bash
set -euo pipefail

: "${TAG:?}"
: "${VERSION:?}"
: "${CHANNEL:?}"
: "${ARCHIVE:?}"
: "${SIDECAR:?}"
: "${NOTES:?}"
: "${REPOSITORY:?}"
: "${COMMIT:?}"

remote_tag="$(git ls-remote --tags origin "refs/tags/$TAG" | awk '{print $1}')"
peeled="$(git ls-remote --tags origin "refs/tags/$TAG^{}" | awk '{print $1}')"
if [[ -n "$remote_tag" ]]; then
  if [[ -z "$peeled" || "$peeled" != "$COMMIT" ]]; then
    echo "Existing tag $TAG is not an annotated tag for $COMMIT." >&2
    exit 1
  fi
else
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git tag -a "$TAG" "$COMMIT" -m "Release $TAG"
  git push origin "refs/tags/$TAG"
fi

release_json="$(mktemp)"
load_release() {
  gh release view "$TAG" --repo "$REPOSITORY" \
    --json databaseId,name,body,isDraft,assets |
    jq '. + {id: .databaseId}'
}

if load_release >"$release_json" 2>/dev/null; then
  if [[ "$(jq -r .draft "$release_json")" != "true" ]]; then
    echo "Published release $TAG already exists and will not be modified." >&2
    exit 1
  fi
else
  gh release create "$TAG" --draft --verify-tag \
    --title "LoxBerry MCP Server $VERSION" --notes-file "$NOTES"
  load_release >"$release_json"
fi

expected_title="LoxBerry MCP Server $VERSION"
expected_body="$(cat "$NOTES")"
actual_title="$(jq -r '.name // ""' "$release_json")"
actual_body="$(jq -r '.body // ""' "$release_json")"
if [[ "$actual_title" != "$expected_title" || "$actual_body" != "$expected_body" ]]; then
  echo "Draft release title or notes do not match the verified release metadata." >&2
  exit 1
fi

expected_names="$(printf '%s\n%s\n' "$(basename "$ARCHIVE")" "$(basename "$SIDECAR")" | sort)"
actual_names="$(jq -r '.assets[].name' "$release_json" | sort)"
unexpected="$(comm -13 <(printf '%s\n' "$expected_names") <(printf '%s\n' "$actual_names"))"
if [[ -n "$unexpected" ]]; then
  echo "Draft release contains unexpected assets: $unexpected" >&2
  exit 1
fi

for asset in "$ARCHIVE" "$SIDECAR"; do
  name="$(basename "$asset")"
  asset_id="$(jq -r --arg name "$name" '.assets[] | select(.name == $name) | .id' "$release_json")"
  if [[ -n "$asset_id" ]]; then
    downloaded="$(mktemp)"
    gh api -H "Accept: application/octet-stream" \
      "repos/$REPOSITORY/releases/assets/$asset_id" >"$downloaded"
    if [[ "$(sha256sum "$downloaded" | awk '{print $1}')" != "$(sha256sum "$asset" | awk '{print $1}')" ]]; then
      echo "Existing draft asset $name has different bytes." >&2
      exit 1
    fi
  else
    gh release upload "$TAG" "$asset"
  fi
done

load_release >"$release_json"
for asset in "$ARCHIVE" "$SIDECAR"; do
  name="$(basename "$asset")"
  asset_id="$(jq -r --arg name "$name" '.assets[] | select(.name == $name) | .id' "$release_json")"
  [[ -n "$asset_id" ]] || { echo "Missing uploaded asset $name." >&2; exit 1; }
  downloaded="$(mktemp)"
  gh api -H "Accept: application/octet-stream" \
    "repos/$REPOSITORY/releases/assets/$asset_id" >"$downloaded"
  [[ "$(sha256sum "$downloaded" | awk '{print $1}')" == "$(sha256sum "$asset" | awk '{print $1}')" ]] ||
    { echo "Uploaded asset $name failed hash verification." >&2; exit 1; }
done

release_id="$(jq -r .id "$release_json")"
if [[ "$CHANNEL" == "prerelease" ]]; then
  gh api --method PATCH "repos/$REPOSITORY/releases/$release_id" \
    -F draft=false -F prerelease=true -f make_latest=false >/dev/null
else
  gh api --method PATCH "repos/$REPOSITORY/releases/$release_id" \
    -F draft=false -F prerelease=false -f make_latest=true >/dev/null
fi
