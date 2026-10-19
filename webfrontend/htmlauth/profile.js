/* Profile UI: exact source selection and explicit user declarations. */
(function () {
  "use strict";
  const page = document.getElementById("profile-page");
  if (!page) return;
  const get = (id) => document.getElementById(`profile-${id}`);
  let revision = 0, installation = "", bindingId = "", nextOffset = null;
  let sources = [];
  let profileBindings = [];
  let deleting = false;
  const dialog = get("confirm");
  function ask(text, title, action) {
    return new Promise((resolve) => {
      get("confirm-message").textContent = text;
      get("confirm-title").textContent = title;
      get("confirm-action").textContent = action;
      dialog.returnValue = "cancel";
      dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
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
      if (!await ask(id === null ? page.dataset.deleteAllConfirm : page.dataset.deleteBindingConfirm, page.dataset.deleteConfirmTitle, page.dataset.delete)) return;
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
  async function loadPermissions() {
    const result = await call("profile_permissions", {});
    get("permission-enabled").checked = result.enabled;
    get("permission-client").replaceChildren();
    for (const session of result.sessions) {
      const option = document.createElement("option");
      option.value = session.id; option.textContent = session.label;
      option.disabled = session.approved;
      get("permission-client").append(option);
    }
    get("permission-allow").disabled = !result.sessions.some((session) => !session.approved);
    const candidate = result.sessions.find((session) => !session.approved);
    if (candidate) get("permission-client").value = candidate.id;
    get("permission-bindings").replaceChildren();
    for (const binding of result.bindings) {
      const row = document.createElement("li");
      row.append(document.createTextNode(`${binding.slice(0, 12)} `));
      const revoke = document.createElement("button"); revoke.type = "button";
      revoke.textContent = page.dataset.permissionRevoke;
      revoke.addEventListener("click", () => changePermission("profile_permission_revoke", { binding_id: binding }, revoke));
      row.append(revoke); get("permission-bindings").append(row);
    }
    get("permission-fields").disabled = false;
  }
  async function changePermission(action, payload, opener) {
    if (deleting) return;
    deleting = true;
    try {
      const target = action === "profile_permission_allow"
        ? get("permission-client").selectedOptions[0]?.textContent || ""
        : action === "profile_permission_revoke" ? payload.binding_id.slice(0, 12)
          : payload.enabled ? page.dataset.permissionEnabled : page.dataset.permissionDisabled;
      if (!await ask(`${page.dataset.permissionConfirm}\n${opener.textContent}\n${target}`, page.dataset.permissionTitle, opener.textContent)) return;
      get("permission-fields").disabled = true;
      await call(action, { ...payload, confirm: true });
      await loadPermissions(); message("saved");
    } catch (_) { message("error"); }
    finally {
      deleting = false; get("permission-fields").disabled = false;
      (opener.isConnected ? opener : get("permission-save")).focus();
    }
  }
  get("permission-save").addEventListener("click", () => changePermission("profile_permission_enable", { enabled: get("permission-enabled").checked }, get("permission-save")));
  get("permission-allow").addEventListener("click", () => changePermission("profile_permission_allow", { session_id: get("permission-client").value }, get("permission-allow")));
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
    validatePVRange(get("pv-capacity"));
    get("pv-arrays").replaceChildren();
    get("flex-windows").replaceChildren();
    get("form").querySelector('button[type="submit"]').disabled = false;
    selectSource();
    configureFields();
  }
  function configureFields() {
    const weather = get("kind").value === "weather";
    get("control").required = !weather; get("control").disabled = weather;
    get("weather-fields").hidden = !weather; get("weather-fields").disabled = !weather;
    if (weather) get("role").value = "weather_context";
    else if (get("role").value === "weather_context") get("role").value = "production";
    get("role").disabled = weather;
    get("boundary").disabled = weather; get("direction").disabled = weather;
    const production = !weather && get("role").value === "production";
    get("pv-section").hidden = !production;
    get("pv-fields").disabled = !production || !get("pv-enabled").checked;
    const consumer = !weather && get("role").value === "consumer";
    get("flex-section").hidden = !consumer;
    const flexible = consumer && get("flex-enabled").checked;
    get("flex-fields").disabled = !flexible;
    const declared = flexible && get("flex-origin").value === "user_declared";
    get("flex-energy").disabled = !declared;
    get("flex-energy").required = declared;
    get("flex-enabled").setCustomValidity(flexible && !get("flex-windows").children.length ? page.dataset.flexError : "");
    const value = Number(get("flex-energy").value);
    get("flex-energy").setCustomValidity(declared && get("flex-energy").value !== "" && (!Number.isFinite(value) || value <= 0) ? page.dataset.flexError : "");
  }
  function operatingOptions(selected = get("flex-operating").value) {
    const select = get("flex-operating"); select.replaceChildren();
    const empty = document.createElement("option"); empty.value = "";
    empty.textContent = page.dataset.flexUnavailable; select.append(empty);
    for (const binding of profileBindings.filter((b) => b.load_operating_source_eligible)) {
      const option = document.createElement("option"); option.value = binding.binding_id;
      const source = sources.find((s) => s.control_uuid === binding.control_uuid && s.source_id === binding.state_uuid);
      option.textContent = `${binding.control_name} · ${source?.source_name || binding.binding_id}`;
      select.append(option);
    }
    if (selected && ![...select.options].some((o) => o.value === selected)) {
      const unavailable = document.createElement("option"); unavailable.value = selected;
      unavailable.textContent = page.dataset.flexUnavailable; unavailable.disabled = true; select.append(unavailable);
    }
    select.value = selected || "";
  }
  function validateWindow(row) {
    const days = [...row.querySelectorAll("[data-weekday]")];
    days[0].setCustomValidity(days.some((d) => d.checked) ? "" : page.dataset.flexError);
    const start = row.querySelector('[data-key="start"]').value;
    const end = row.querySelector('[data-key="end"]');
    const minutes = (value) => value.split(":").reduce((hours, part) => hours * 60 + Number(part), 0);
    const length = end.value && start ? minutes(end.value) + 1440 * Number(row.querySelector('[data-key="end_day_offset"]').value) - minutes(start) : null;
    end.setCustomValidity(length !== null && !(length > 0 && length <= 1440) ? page.dataset.flexError : "");
  }
  function addWindow(value = {}) {
    if (get("flex-windows").children.length >= 16) return;
    const row = get("flex-window-template").content.firstElementChild.cloneNode(true);
    for (const input of row.querySelectorAll("[data-weekday]")) {
      input.checked = (value.weekdays || []).includes(Number(input.value));
      input.addEventListener("change", () => validateWindow(row));
    }
    for (const input of row.querySelectorAll("[data-key]")) input.value = value[input.dataset.key] ?? (input.tagName === "SELECT" ? "0" : "");
    row.querySelector("[data-remove]").addEventListener("click", () => {
      row.remove(); get("confirmed").checked = false; get("flex-add-window").focus();
      configureFields();
    });
    get("flex-windows").append(row); validateWindow(row); configureFields();
    for (const type of ["input", "change"]) row.addEventListener(type, () => validateWindow(row));
  }
  function loadFlexibility() {
    if (get("role").value !== "consumer" || !get("flex-enabled").checked) return null;
    return {
      timezone: get("flex-timezone").value,
      operating_binding_id: get("flex-operating").value,
      cycle_identity: get("flex-identity").value,
      latest_completion: get("flex-completion").value,
      completion_day_offset: Number(get("flex-completion-day").value),
      duration_seconds: Number(get("flex-duration").value),
      interruptible: get("flex-interruptible").checked,
      minimum_run_seconds: Number(get("flex-min-run").value),
      minimum_off_seconds: Number(get("flex-min-off").value),
      energy_profile_origin: get("flex-origin").value,
      declared_cycle_energy_wh: get("flex-origin").value === "user_declared" ? numberOrNull(get("flex-energy")) : null,
      rationale: get("flex-rationale").value,
      native_lock_policy: "never_override",
      windows: [...get("flex-windows").children].map((row) => ({
        weekdays: [...row.querySelectorAll("[data-weekday]:checked")].map((d) => Number(d.value)),
        start: row.querySelector('[data-key="start"]').value,
        end: row.querySelector('[data-key="end"]').value,
        end_day_offset: Number(row.querySelector('[data-key="end_day_offset"]').value),
      })),
    };
  }
  function addArray(value = {}) {
    if (get("pv-arrays").children.length >= 16) return;
    const row = get("pv-array-template").content.firstElementChild.cloneNode(true);
    for (const input of row.querySelectorAll("[data-key]")) input.value = value[input.dataset.key] ?? "";
    for (const input of row.querySelectorAll("[data-positive], [data-exclusive-max]")) {
      input.addEventListener("input", () => validatePVRange(input)); validatePVRange(input);
    }
    row.querySelector("[data-remove]").addEventListener("click", () => { row.remove(); get("pv-add-array").focus(); });
    get("pv-arrays").append(row);
  }
  function validatePVRange(input) {
    const value = Number(input.value);
    const valid = input.value === "" || (Number.isFinite(value) &&
      (!input.hasAttribute("data-positive") || value > 0) &&
      (!input.hasAttribute("data-exclusive-max") || value < Number(input.dataset.exclusiveMax)));
    input.setCustomValidity(valid ? "" : page.dataset.pvRangeError);
  }
  const numberOrNull = (input) => input.value === "" ? null : Number(input.value);
  function pvParameters() {
    if (get("role").value !== "production" || !get("pv-enabled").checked) return null;
    return {
      installed_kwp: numberOrNull(get("pv-capacity")),
      latitude: numberOrNull(get("pv-latitude")), longitude: numberOrNull(get("pv-longitude")),
      arrays: [...get("pv-arrays").children].map((row) => {
        const array = {};
        for (const input of row.querySelectorAll("[data-key]")) {
          array[input.dataset.key] = input.type === "number" ? numberOrNull(input) : input.value || null;
        }
        return array;
      }),
    };
  }
  function selectSource() {
    const source = sources[Number(get("source").value)];
    if (!source) return;
    get("control").value = source.control_uuid || "";
    get("kind").value = source.source_kind;
    get("source-id").value = source.source_id;
    if (source.source_kind === "weather") {
      get("weather-mode").value = source.mode; get("weather-field").value = source.field;
    }
    configureFields();
  }
  function edit(binding) {
    bindingId = binding.binding_id;
    get("control").value = binding.control_uuid || "";
    get("kind").value = binding.source_kind;
    get("source-id").value = binding.weather_state_uuid || binding.state_uuid || binding.series_id || "";
    get("role").value = binding.role;
    get("boundary").value = binding.measurement_boundary || "";
    get("direction").value = binding.declared_direction || "";
    get("rationale").value = binding.rationale || "";
    get("confirmed").checked = false;
    get("weather-mode").value = binding.mode || "actual";
    get("weather-field").value = binding.field || "temperature";
    const pv = binding.pv_parameters;
    get("pv-enabled").checked = Boolean(pv);
    get("pv-capacity").value = pv?.installed_kwp ?? "";
    validatePVRange(get("pv-capacity"));
    get("pv-latitude").value = pv?.latitude ?? ""; get("pv-longitude").value = pv?.longitude ?? "";
    get("pv-arrays").replaceChildren();
    for (const array of pv?.arrays || []) addArray(array);
    const flex = binding.load_flexibility;
    get("flex-enabled").checked = Boolean(flex);
    get("flex-timezone").value = flex?.timezone || "";
    operatingOptions(flex?.operating_binding_id || "");
    get("flex-identity").value = flex?.cycle_identity || "active_episode_only";
    get("flex-completion").value = flex?.latest_completion || "";
    get("flex-completion-day").value = String(flex?.completion_day_offset || 0);
    get("flex-duration").value = flex?.duration_seconds ?? "";
    get("flex-interruptible").checked = Boolean(flex?.interruptible);
    get("flex-min-run").value = flex?.minimum_run_seconds ?? 0;
    get("flex-min-off").value = flex?.minimum_off_seconds ?? 0;
    get("flex-origin").value = flex?.energy_profile_origin || "observed_intervals";
    get("flex-energy").value = flex?.declared_cycle_energy_wh ?? "";
    get("flex-rationale").value = flex?.rationale || "";
    get("flex-windows").replaceChildren();
    for (const window of flex?.windows || []) addWindow(window);
    get("form").querySelector('button[type="submit"]').disabled = Boolean(binding.load_constraints_present && !flex);
    if (binding.load_constraints_present && !flex) message("flexUnavailable");
    configureFields();
    const index = sources.findIndex((s) => s.source_kind === binding.source_kind &&
      s.control_uuid === binding.control_uuid && s.source_id === get("source-id").value &&
      (s.source_kind !== "weather" || (s.mode === binding.mode && s.field === binding.field)));
    get("source").value = index >= 0 ? String(index) : "";
    get("exact").open = index < 0;
    get("fields").scrollIntoView({ block: "start", behavior: "smooth" });
  }
  function append(bindings) {
    for (const binding of bindings) {
      const row = document.createElement("li");
      const label = document.createElement("span");
      const role = [...get("role").options].find((option) => option.value === binding.role);
      const name = binding.source_kind === "weather" ? [...get("weather-field").options].find((option) => option.value === binding.field)?.textContent : binding.control_name;
      label.textContent = `${name || ""} · ${role ? role.textContent : ""} · ${page.dataset[binding.status] || ""} `;
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
      profileBindings = [];
      get("bindings").replaceChildren();
      sources = result.sources;
      get("source").replaceChildren();
      sources.forEach((source, index) => {
        const option = document.createElement("option"); option.value = String(index);
        option.textContent = source.source_kind === "weather"
          ? `${[...get("weather-mode").options].find((o) => o.value === source.mode)?.textContent} · ${[...get("weather-field").options].find((o) => o.value === source.field)?.textContent}`
          : `${source.control_name} · ${source.source_name}`;
        get("source").append(option);
      });
      get("source-notice").textContent = result.sources_truncated ? page.dataset.truncated : "";
      if (!bindingId) selectSource();
    }
    profileBindings.push(...result.bindings); operatingOptions();
    append(result.bindings); nextOffset = result.next_offset;
    get("more").hidden = nextOffset === null;
    if (!offset && !result.bindings.length) message("empty");
    get("fields").disabled = result.status !== "available";
    get("delete-all").disabled = false;
    if (result.status !== "available") message("error");
  }
  get("source").addEventListener("change", selectSource);
  get("kind").addEventListener("change", configureFields);
  get("role").addEventListener("change", configureFields);
  get("pv-enabled").addEventListener("change", configureFields);
  get("flex-enabled").addEventListener("change", () => {
    if (get("flex-enabled").checked && !get("flex-windows").children.length) addWindow();
    configureFields();
  });
  get("flex-origin").addEventListener("change", configureFields);
  get("flex-energy").addEventListener("input", configureFields);
  get("flex-add-window").addEventListener("click", () => { addWindow(); get("confirmed").checked = false; });
  for (const type of ["input", "change"]) get("form").addEventListener(type, (event) => {
    if (event.target !== get("confirmed")) get("confirmed").checked = false;
  });
  get("pv-capacity").addEventListener("input", () => validatePVRange(get("pv-capacity")));
  get("pv-add-array").addEventListener("click", () => addArray());
  get("new").addEventListener("click", reset);
  get("delete-all").addEventListener("click", () => deleteBinding(null, get("delete-all")));
  get("more").addEventListener("click", async () => {
    get("more").disabled = true;
    try { if (nextOffset !== null) await load(nextOffset); } catch (_) { message("error"); }
    finally { get("more").disabled = false; }
  });
  get("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (get("form").querySelector('button[type="submit"]').disabled) { message("flexUnavailable"); return; }
    get("fields").disabled = true;
    const kind = get("kind").value;
    const binding = kind === "weather" ? {
      binding_id: bindingId || `b-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
      role: "weather_context", source_kind: "weather", weather_state_uuid: get("source-id").value,
      mode: get("weather-mode").value, field: get("weather-field").value,
      rationale: get("rationale").value, confirmed: get("confirmed").checked,
    } : {
      binding_id: bindingId || `b-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
      role: get("role").value, control_uuid: get("control").value, source_kind: kind,
      state_uuid: kind === "state" ? get("source-id").value : null,
      series_id: kind === "statistic" ? get("source-id").value : null,
      measurement_boundary: get("boundary").value || null,
      declared_direction: get("direction").value || null,
      rationale: get("rationale").value, confirmed: get("confirmed").checked,
      pv_parameters: pvParameters(),
      load_flexibility: loadFlexibility(),
    };
    try { await call("profile_put", { installation, revision, confirm: true, binding }); reset(); await load(); message("saved"); }
    catch (_) { message("error"); }
    finally { get("fields").disabled = false; }
  });
  load().catch(() => message("error"));
  loadPermissions().catch(() => message("error"));
}());
