/* Profile UI: exact source selection and explicit user declarations. */
(function () {
  "use strict";
  const page = document.getElementById("profile-page");
  if (!page) return;
  const get = (id) => document.getElementById(`profile-${id}`);
  let revision = 0, installation = "", bindingId = "", nextOffset = null;
  let sources = [];
  let deleting = false;
  const dialog = get("confirm");
  function askDelete(all) {
    return new Promise((resolve) => {
      get("confirm-message").textContent = all ? page.dataset.deleteAllConfirm : page.dataset.deleteBindingConfirm;
      dialog.returnValue = "cancel";
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), { once: true });
      dialog.showModal();
      get("confirm-cancel").focus();
    });
  }
  async function deleteBinding(id, opener) {
    if (deleting) return;
    deleting = true;
    const payload = { installation, revision, binding_id: id, confirm: true };
    const fieldsDisabled = get("fields").disabled;
    const deleteDisabled = get("delete-all").disabled;
    let loaded = false;
    try {
      if (!await askDelete(id === null)) return;
      get("fields").disabled = true; get("delete-all").disabled = true;
      await call("profile_delete", payload);
      reset(); await load(); message("saved");
      loaded = true;
    } catch (_) { message("error"); }
    finally {
      deleting = false;
      if (!loaded) {
        get("delete-all").disabled = deleteDisabled; get("fields").disabled = fieldsDisabled;
      }
      (opener.isConnected ? opener : get("delete-all")).focus();
    }
  }
  const message = (key) => { get("status").textContent = page.dataset[key] || page.dataset.error; };
  async function call(action, payload) {
    const body = new URLSearchParams({ action, payload: JSON.stringify(payload) });
    const response = await fetch("profile.cgi", { method: "POST", credentials: "same-origin", body, cache: "no-store" });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error("profile_request_rejected");
    return result.data;
  }
  function reset() {
    bindingId = "";
    get("form").reset();
    selectSource();
  }
  function selectSource() {
    const source = sources[Number(get("source").value)];
    if (!source) return;
    get("control").value = source.control_uuid;
    get("kind").value = source.source_kind;
    get("source-id").value = source.source_id;
  }
  function edit(binding) {
    bindingId = binding.binding_id;
    get("control").value = binding.control_uuid;
    get("kind").value = binding.source_kind;
    get("source-id").value = binding.state_uuid || binding.series_id || "";
    get("role").value = binding.role;
    get("boundary").value = binding.measurement_boundary || "";
    get("direction").value = binding.declared_direction || "";
    get("rationale").value = binding.rationale || "";
    get("confirmed").checked = false;
    const index = sources.findIndex((s) => s.control_uuid === binding.control_uuid && s.source_id === get("source-id").value);
    get("source").value = index >= 0 ? String(index) : "";
    get("exact").open = index < 0;
    get("fields").scrollIntoView({ block: "start", behavior: "smooth" });
  }
  function append(bindings) {
    for (const binding of bindings) {
      const row = document.createElement("li");
      const label = document.createElement("span");
      const role = [...get("role").options].find((option) => option.value === binding.role);
      label.textContent = `${binding.control_name} · ${role ? role.textContent : ""} · ${page.dataset[binding.status] || ""} `;
      row.append(label);
      const editButton = document.createElement("button");
      editButton.type = "button"; editButton.textContent = page.dataset.edit;
      editButton.addEventListener("click", () => edit(binding)); row.append(editButton);
      const remove = document.createElement("button");
      remove.type = "button"; remove.textContent = page.dataset.delete;
      remove.addEventListener("click", () => deleteBinding(binding.binding_id, remove));
      row.append(remove); get("bindings").append(row);
    }
  }
  async function load(offset = 0) {
    const result = await call("profile_page", { offset, limit: 100 });
    if (offset && revision !== result.revision) { await load(); return; }
    revision = result.revision; installation = result.installation;
    if (!offset) {
      get("bindings").replaceChildren();
      sources = result.sources;
      get("source").replaceChildren();
      sources.forEach((source, index) => {
        const option = document.createElement("option"); option.value = String(index);
        option.textContent = `${source.control_name} · ${source.source_name}`; get("source").append(option);
      });
      get("source-notice").textContent = result.sources_truncated ? page.dataset.truncated : "";
      if (!bindingId) selectSource();
    }
    append(result.bindings); nextOffset = result.next_offset;
    get("more").hidden = nextOffset === null;
    if (!offset && !result.bindings.length) message("empty");
    get("fields").disabled = result.status !== "available";
    get("delete-all").disabled = false;
    if (result.status !== "available") message("error");
  }
  get("source").addEventListener("change", selectSource);
  get("new").addEventListener("click", reset);
  get("delete-all").addEventListener("click", () => deleteBinding(null, get("delete-all")));
  get("more").addEventListener("click", async () => {
    get("more").disabled = true;
    try { if (nextOffset !== null) await load(nextOffset); } catch (_) { message("error"); }
    finally { get("more").disabled = false; }
  });
  get("form").addEventListener("submit", async (event) => {
    event.preventDefault(); get("fields").disabled = true;
    const kind = get("kind").value;
    const binding = {
      binding_id: bindingId || `b-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
      role: get("role").value, control_uuid: get("control").value, source_kind: kind,
      state_uuid: kind === "state" ? get("source-id").value : null,
      series_id: kind === "statistic" ? get("source-id").value : null,
      measurement_boundary: get("boundary").value || null,
      declared_direction: get("direction").value || null,
      rationale: get("rationale").value, confirmed: get("confirmed").checked,
    };
    try { await call("profile_put", { installation, revision, confirm: true, binding }); reset(); await load(); message("saved"); }
    catch (_) { message("error"); }
    finally { get("fields").disabled = false; }
  });
  load().catch(() => message("error"));
}());
