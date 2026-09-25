/* Static presentation hints for the Tool Explorer. The server owns authorization. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.McpExplorerAdapters = api;
})(typeof window !== 'undefined' ? window : undefined, function () {
  'use strict';

  const GROUPS = [
    {id: 'loxoneRead', scopes: ['loxone:read'], names: [
      'loxone_get_skill_guide', 'loxone_get_system_status', 'loxone_list_rooms',
      'loxone_list_categories', 'loxone_find_controls', 'loxone_describe_control',
      'loxone_get_control_notes', 'loxone_get_states',
      'loxone_get_structure_overview', 'loxone_get_room_snapshot',
      'loxone_list_global_metadata', 'loxone_get_weather', 'loxone_get_project_status',
      'loxone_find_project_objects', 'loxone_describe_project_object',
      'loxone_trace_project_logic', 'loxone_analyze_project',
    ]},
    {id: 'loxoneHistory', scopes: ['loxone:read', 'loxone:history'], names: [
      'loxone_get_statistics', 'loxone_get_control_history', 'loxone_get_state_history',
      'loxone_analyze_observability',
    ]},
    {id: 'loxoneControl', scopes: ['loxone:read', 'loxone:control'], names: [
      'loxone_operate_control',
    ]},
    {id: 'loxberryRead', scopes: ['loxone:read', 'loxberry:read'], names: [
      'loxberry_get_system_status', 'loxberry_get_plugin_status',
      'loxberry_get_service_health', 'loxberry_list_service_events',
    ]},
    {id: 'loxberryOperate', scopes: ['loxone:read', 'loxone:history', 'loxberry:operate'], names: [
      'loxberry_clear_statistics_cache', 'loxberry_list_event_history_sources',
      'loxberry_add_event_history_source', 'loxberry_remove_event_history_source',
      'loxberry_purge_event_history_source',
    ]},
    {id: 'other', scopes: null, names: []},
  ];
  const TOOL_HINTS = new Map();
  GROUPS.forEach((group) => group.names.forEach((name, order) => {
    if (TOOL_HINTS.has(name)) throw new Error(`Duplicate Explorer tool hint: ${name}`);
    TOOL_HINTS.set(name, {group: group.id, order, scopes: group.scopes});
  }));

  const ADVANCED_FIELDS = new Set(['cursor', 'limit', 'include_hidden']);
  const FIELD_HELP = {
    cursor: 'helpCursor', limit: 'helpLimit', query: 'helpQuery',
    room_uuid: 'helpRoomUuid', category_uuid: 'helpCategoryUuid',
    control_type: 'helpControlType', control_uuid: 'helpControlUuid',
    state_uuids: 'helpStateUuids', action: 'helpAction',
  };
  const REFERENCES = {
    control_uuid: [{tool: 'loxone_find_controls', path: ['uuid']}],
    room_uuid: [{tool: 'loxone_list_rooms', path: ['uuid']}],
    category_uuid: [{tool: 'loxone_list_categories', path: ['uuid']}],
    room_group_uuid: [{tool: 'loxone_list_rooms', path: ['room_group', 'uuid'], namePath: ['room_group', 'name']}],
  };
  const ACTION_FIELDS = {
    set_level: ['level'], set_mood: ['mood_id'], set_position: ['position'],
    set_slat_position: ['slat_position'], set_position_and_slats: ['position', 'slat_position'],
    select_output: ['output_id'], set_scene: ['scene_id'],
    set_color_hsv: ['hue', 'saturation', 'brightness'],
    set_color_temperature: ['brightness', 'kelvin'],
    set_value: ['value'], start_override: ['value', 'duration_seconds'],
    start_fan_override: ['duration_seconds'],
    start_mode_override: ['value', 'duration_seconds'],
  };
  const OPERATION_FIELDS = [...new Set(Object.values(ACTION_FIELDS).flat())];

  function forTool(tool) {
    return TOOL_HINTS.get(typeof tool === 'string' ? tool : tool && tool.name) || null;
  }

  function toolGroup(tool) {
    return forTool(tool)?.group || 'other';
  }

  function requiredScopes(tool) {
    return forTool(tool)?.scopes || null;
  }

  function requiredMutationScope(tool) {
    const scopes = requiredScopes(tool);
    return scopes && (scopes.includes('loxberry:operate') ? 'loxberry:operate'
      : scopes.includes('loxone:control') ? 'loxone:control' : null);
  }

  function fieldHelpKey(name) { return FIELD_HELP[name] || null; }
  function isAdvancedField(name) { return ADVANCED_FIELDS.has(name); }
  function isReferenceField(name) { return Object.hasOwn(REFERENCES, name); }
  function actionFields(action) { return ACTION_FIELDS[action] || []; }
  function operationParameterFields() { return OPERATION_FIELDS; }
  function hasActionFields(tool) { return (typeof tool === 'string' ? tool : tool?.name) === 'loxone_operate_control'; }

  function fieldVisible(tool, field, argumentsValue) {
    if (!hasActionFields(tool)) return true;
    return field === 'control_uuid' || field === 'action' ||
      actionFields(argumentsValue && argumentsValue.action).includes(field);
  }

  function changeAction(argumentsValue, action) {
    const next = {...argumentsValue, action};
    const visible = new Set(actionFields(action));
    OPERATION_FIELDS.forEach((field) => { if (!visible.has(field)) delete next[field]; });
    return next;
  }

  function referenceCandidates(field, history) {
    const sources = REFERENCES[field];
    if (!sources || !Array.isArray(history)) return [];
    const candidates = new Map();
    const at = (item, path) => path.reduce((value, key) => value && value[key], item);
    for (const entry of [...history].reverse()) {
      const result = entry && entry.result;
      const displayed = result && (result.structuredContent ?? result.content ?? result);
      const data = displayed && displayed.data;
      if (!data || !Array.isArray(data.items)) continue;
      for (const source of sources.filter((candidate) => candidate.tool === entry.tool)) {
        for (const item of data.items) {
          if (!item || typeof item !== 'object') continue;
          const value = at(item, source.path);
          if (typeof value !== 'string' || !value || candidates.has(value)) continue;
          const name = at(item, source.namePath || ['name']);
          candidates.set(value, {value, label: name ? `${name} (${value})` : value});
        }
      }
    }
    return [...candidates.values()];
  }

  // Recipes enhance a transfer; schema-compatible targets remain the default.
  const TRANSFER_RECIPES = [{
    sourceTool: 'loxone_describe_control',
    targetTool: 'loxone_get_statistics',
    contextLabel: 'statisticsTransferContext',
    prepare(displayedResult, path, value, now) {
      if (!Array.isArray(path) || path.length !== 4 ||
        path[0] !== 'data' || path[1] !== 'capabilities' || path[2] !== 'statistics' ||
        !value || typeof value !== 'object' || Array.isArray(value) ||
        typeof value.series_id !== 'string' || !displayedResult || !displayedResult.data ||
        typeof displayedResult.data.uuid !== 'string') return null;
      const end = new Date(now === undefined ? Date.now() : now);
      if (Number.isNaN(end.getTime())) return null;
      return {
        control_uuid: displayedResult.data.uuid,
        series_id: value.series_id,
        start: new Date(end.getTime() - 24 * 60 * 60 * 1000).toISOString(),
        end: end.toISOString(),
        granularity: 'raw',
      };
    },
  }];

  function transferRecipe(sourceTool, displayedResult, path, value, tools, now) {
    for (const recipe of TRANSFER_RECIPES) {
      if (recipe.sourceTool !== sourceTool ||
          !tools.some((tool) => tool.name === recipe.targetTool)) continue;
      const args = recipe.prepare(displayedResult, path, value, now);
      if (args) return {tool: recipe.targetTool, arguments: args, contextLabel: recipe.contextLabel};
    }
    return null;
  }

  return {GROUPS, forTool, toolGroup, requiredScopes, requiredMutationScope,
    fieldHelpKey, isAdvancedField, isReferenceField, referenceCandidates,
    hasActionFields, actionFields, operationParameterFields, fieldVisible, changeAction,
    transferRecipe};
});
