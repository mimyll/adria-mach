/** Adria MACH dashboard cards for Home Assistant. */
const BRAND = "Adria MACH";
const DOMAIN = "adria_mach";
const PRESETS = [20, 40, 60, 80, 100];
const LIGHT_KEYS = Array.from({ length: 8 }, (_, index) => `light_group_${index + 1}`);
const LIGHT_ROLES = ["outside_light", "light_master", ...LIGHT_KEYS, "aux_output"];
const PICKER = {
  overview: ["Overview", "Tilanne"],
  heating: ["Heating", "Lämmitys"],
  lights: ["Lights", "Valot"],
  energy: ["Water and energy", "Vesi ja energia"],
};
const WORDS = {
  vehicle: ["Adria device", "Adria-laite"],
  choose: ["Select your Adria MACH device.", "Valitse Adria MACH -laite."],
  inside: ["Inside", "Sisällä"],
  outside: ["Outside", "Ulkona"],
  linked: ["MACH connection", "MACH-yhteys"],
  age: ["Time since HA read", "Aikaa HA:n luvusta"],
  mains: ["230 V shore power", "230 V verkkovirta"],
  battery: ["Battery", "Akku"],
  fresh: ["Fresh water", "Raikasvesi"],
  waste: ["Waste water", "Harmaavesi"],
  fridge: ["Refrigerator", "Jääkaappi"],
  source: ["Energy source", "Energialähde"],
  priority: ["Energy priority", "Energiaprioriteetti"],
  spot: ["Spot-price heating control", "Pörssisähköohjaus"],
  target: ["Heating setpoint", "Lämmityksen pyynti"],
  groups: ["Other lights", "Muut valot"],
  equipment: ["Refrigerator, gas and water details", "Jääkaapin, kaasun ja veden tiedot"],
  gas: ["Gas bottle level", "Kaasupullon täyttöaste"],
  noGas: ["No measurement", "Ei mittaustietoa"],
  location: ["Caravan location (GPS)", "Vaunun sijainti (GPS)"],
  noLocation: ["Position unavailable", "Sijaintia ei saatavilla"],
  level: ["Caravan levelling", "Vaunun tasaus"],
  brightness: ["Brightness", "Kirkkaus"],
  turnOn: ["Turn on", "Sytytä"],
  turnOff: ["Turn off", "Sammuta"],
  insideOff: ["All off · interior", "Kaikki pois · sisävalot"],
  allOff: ["All off + exterior lights", "Kaikki pois + ulkovalot"],
  pending: ["Request pending", "Pyyntö odottaa"],
  done: ["Request completed", "Pyyntö käsitelty"],
  failed: ["Request failed or unconfirmed", "Pyyntö epäonnistui tai jäi vahvistamatta"],
  partial: ["Shutdown interrupted. Some lights may remain on.", "Sammutus keskeytyi. Osa valoista voi yhä olla päällä."],
  unavailable: ["Unavailable", "Ei saatavilla"],
  names: ["Light names and icons", "Valojen nimet ja kuvakkeet"],
  name: ["Display name", "Näyttönimi"],
  icon: ["Icon", "Kuvake"],
  gps: ["Show GPS map", "Näytä GPS-kartta"],
  includeAux: ["Include configured AUX rear lights", "Sisällytä AUX-takavalot"],
  on: ["On", "Päällä"],
  off: ["Off", "Pois"],
  someOn: ["Some on", "Osa päällä"],
  tapOff: ["Tap to turn off", "Painallus sammuttaa"],
  interior: ["Interior lights", "Sisävalot"],
  allLights: ["Interior and exterior lights", "Sisä- ja ulkovalot"],
  lightGroups: ["Light groups and rear light", "Valoryhmät ja takavalo"],
  heatSettings: ["Heating settings", "Lämmitysasetukset"],
  hotWater: ["Hot water", "Käyttövesi"],
  price: ["Control price incl. VAT", "Ohjauksen hinta sis. alv"],
  supplies: ["Caravan status", "Vaunun tiedot"],
  charge: ["Battery charge", "Akun varaus"],
  batteryDetails: ["Battery details", "Akun tiedot"],
  designCapacity: ["Nominal capacity", "Nimelliskapasiteetti"],
  storedEnergy: ["Stored energy", "Varastoitu energia"],
  voltage: ["Voltage", "Jännite"],
  current: ["Current", "Virta"],
  batteryTemperature: ["Battery temperature", "Akun lämpötila"],
  runtime: ["Estimated runtime", "Arvioitu käyttöaika"],
  charging: ["Charging", "Latautuu"],
  discharging: ["Discharging", "Purkautuu"],
  idleBattery: ["Not charging", "Ei latausta"],
  cylinders: ["Gas cylinders", "Kaasupullot"],
  gasMissing: ["No reading", "Ei mittausta"],
  calibrate: ["Calibration requested", "Kalibrointia pyydetty"],
  lowGas: ["Low gas", "Kaasua vähän"],
  gasError: ["Sensor error", "Anturivirhe"],
  gasEstimate: ["Estimated empty", "Arvio tyhjenemisestä"],
  appliances: ["Appliances", "Laitteet"],
  pump: ["Water pump", "Vesipumppu"],
  fridgeLevel: ["Cooling level", "Jäähdytystaso"],
  fridgeAuto: ["Refrigerator automatic mode", "Jääkaapin automatiikka"],
  dimensions: ["Caravan dimensions", "Vaunun mitat"],
  length: ["Overall length with drawbar", "Kokonaispituus aisalla"],
  width: ["Width", "Leveys"],
  height: ["Height", "Korkeus"],
  notMeasuring: ["Measurement off", "Mittaus ei käynnissä"],
  lateral: ["Side-to-side height difference", "Sivusuunnan korkeusero"],
  longitudinal: ["Front-to-back height difference", "Pituussuunnan korkeusero"],
};

function finnish(hass) {
  return String(hass?.locale?.language ?? hass?.language ?? "").startsWith("fi");
}

function label(hass, pair) {
  return pair[finnish(hass) ? 1 : 0];
}

function element(tag, text, properties) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return Object.assign(node, properties);
}

function icon(name) {
  const node = element("ha-icon");
  node.setAttribute("icon", name);
  node.setAttribute("aria-hidden", "true");
  return node;
}

function vehicleRecords(hass) {
  return Object.values(hass?.entities ?? {}).filter(
    (entry) => entry.platform === DOMAIN && entry.device_id && !entry.hidden && !entry.hidden_by,
  );
}

function deviceIds(hass) {
  return [...new Set(vehicleRecords(hass).map((entry) => entry.device_id))];
}

function vehicleName(hass, id) {
  const device = hass?.devices?.[id];
  return device?.name_by_user || device?.name || BRAND;
}

function scope(hass, configuredDevice) {
  const ids = deviceIds(hass);
  const device = configuredDevice ?? (ids.length === 1 ? ids[0] : undefined);
  const matches = new Map();
  for (const entry of vehicleRecords(hass)) {
    if (entry.device_id !== device || !entry.translation_key) continue;
    const key = `${entry.entity_id.split(".")[0]}:${entry.translation_key}`;
    matches.set(key, matches.has(key) ? null : entry.entity_id);
  }
  return { device, matches };
}

function entityName(hass, id) {
  const entry = hass?.entities?.[id];
  return entry?.name || entry?.original_name || hass?.states?.[id]?.attributes?.friendly_name || id;
}

function usable(state, stateless = false) {
  return Boolean(state && state.state !== "unavailable" && (stateless || state.state !== "unknown"));
}

function measured(state, unit) {
  if (!usable(state) || !state.state?.trim() || state.attributes.unit_of_measurement !== unit) return null;
  const value = Number(state.state);
  return Number.isFinite(value) ? value : null;
}

function reportedPower(state) {
  if (!usable(state)) return null;
  const reported = "reported_state" in state.attributes
    ? state.attributes.reported_state
    : state.attributes.request_pending ? null : state.state;
  return ["on", "off"].includes(reported) ? reported : null;
}

function readyToControl(state, stateless = false, allowResync = true) {
  const lock = state?.attributes.control_lock_reason;
  const resync = allowResync && ["fresh_manual_resync_required", "fresh_light_resync_required"].includes(lock);
  return usable(state, stateless) && !state.attributes.request_pending
    && !state.attributes.command_in_progress && !state.attributes.pending_control_requests
    && state.attributes.controls_blocked !== true
    && (state.attributes.connection_ready !== false || resync)
    && (!lock || lock === "none" || resync);
}

function shutdownSteps(lookup, includeExterior, includeAux) {
  const master = lookup("button", "all_lights_off");
  if (!master) return [];
  const steps = [["button", "press", master]];
  if (includeExterior) {
    const outside = lookup("light", "outside_light");
    const rear = includeAux && lookup("switch", "aux_output");
    if (includeAux && !rear) return [];
    if (outside) steps.push(["light", "turn_off", outside]);
    if (rear) steps.push(["switch", "turn_off", rear]);
    if (steps.length === 1) return [];
  }
  return steps;
}

const STYLE = `
  :host { display:block; }
  ha-card { min-width:0; box-sizing:border-box; padding:12px; }
  .layout { display:grid; gap:14px; }
  .caravan {
    max-width:1064px; margin:auto; padding:16px; border-radius:16px;
    color-scheme:light dark;
    color:light-dark(#20382e,#e6efe9); background:light-dark(#f2f5f2,#101b18);
    --caravan-line:light-dark(#dce5dd,#34483c);
    --caravan-active:light-dark(#236346,#a4d9bc);
  }
  .caravan ha-card {
    padding:14px; border-radius:16px; border:1px solid var(--caravan-line);
    color:inherit; background:light-dark(#fff,#1b2924);
    --divider-color:var(--caravan-line);
  }
  .caravan .wide { grid-column:1/-1; }
  @media (min-width:760px) { .caravan { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  h2,h3 { color:inherit; font-weight:600; }
  h2 { margin:0; font-size:25px; }
  h3 { margin:0 0 8px; font-size:16px; display:flex; gap:8px; align-items:center; }
  ha-icon { --mdc-icon-size:17px; flex:none; }
  .tiles { display:grid; gap:6px; }
  .temps { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
  .summary-pair { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:center; gap:8px; border-top:1px solid var(--divider-color); }
  .summary-pair .row { border:0; }
  .hero { font-size:clamp(24px,5vw,36px); display:block; line-height:1.2; font-variant-numeric:tabular-nums; }
  .row { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:6px; min-height:44px; padding:3px 0; }
  .row+.row, details+details { border-top:1px solid var(--divider-color,var(--divider-color-default,#8884)); }
  .label { display:inline-flex; flex:1; align-items:center; gap:6px; min-width:0; overflow-wrap:anywhere; }
  .controls { display:inline-flex; flex-wrap:wrap; align-items:center; gap:6px; }
  .actions { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px; }
  button,select,input { font:inherit; color:inherit; }
  button,select {
    min-height:44px; max-width:100%; box-sizing:border-box; padding:4px 9px;
    border-radius:8px; border:1px solid var(--divider-color);
    background:var(--card-background-color,var(--primary-background-color)); cursor:pointer;
  }
  button:disabled,select:disabled { opacity:.56; cursor:default; }
  .active { color:var(--caravan-active,var(--primary-color)); font-weight:600; }
  .hint { font-size:.88em; color:var(--secondary-text-color); }
  .caravan .hint { color:light-dark(#526b5c,#adc0b5); }
  .status { min-height:0; overflow-wrap:anywhere; }
  .status:empty { display:none; }
  summary { min-height:44px; align-content:center; cursor:pointer; font-weight:550; }
  a { color:var(--caravan-active,var(--primary-color)); display:inline-block; line-height:44px; }
  .editor { display:grid; gap:10px; }
  .editor label { display:grid; gap:4px; }
  .editor input { width:100%; box-sizing:border-box; min-height:40px; }
  .editor .check { display:flex; align-items:center; }
  .editor input[type=checkbox] { width:auto; }
`;

const CARAVAN_STYLE = `
  .rv { gap:10px; align-items:start; padding:clamp(10px,2.7%,24px); border-radius:18px;
    background:light-dark(#f5f4f0,#181b1b); color:light-dark(#252b29,#f0f2ee);
    --rv-dim:light-dark(#59615b,#b9c1ba); --rv-inset:light-dark(#f0f1ed,#2b302e);
    --rv-idle:light-dark(#747d77,#8d9992); --rv-knob:light-dark(#fff,#18241c);
    --caravan-line:light-dark(#e0e2dc,#3b4240); --caravan-active:light-dark(#32664c,#95cbaa);
    --rv-lamp:light-dark(#845519,#e9bb76); --rv-lamp-bg:light-dark(#f7ecd7,#433525);
    font-variant-numeric:tabular-nums; }
  .rv ha-card { background:light-dark(#fff,#222626); padding:12px 14px 4px; overflow:visible; }
  .rv .hint,.rv small { color:var(--rv-dim); font-size:12px; }
  .rv header h2 { display:flex; align-items:center; gap:9px; font-size:26px; }
  .rv header ha-icon { --mdc-icon-size:24px; color:var(--rv-dim); }
  .rv header p { display:flex; align-items:center; flex-wrap:wrap; gap:5px; margin:4px 0 0; }
  .rv-dot { width:7px; height:7px; border-radius:50%; background:var(--rv-idle); }
  .rv-dot.ok { background:var(--caravan-active); }
  .rv .temps { align-items:end; padding:4px 0 12px; border-bottom:1px solid var(--caravan-line); }
  .rv .temps .label { color:var(--rv-dim); font-size:12px; }
  .rv .hero { font-size:clamp(30px,5vw,42px); letter-spacing:-.04em; }
  .rv .temps>div+div .hero { font-size:28px; }
  .rv .row { padding:0; box-sizing:border-box; }
  .rv .label { gap:8px; }
  .rv .controls { flex-wrap:nowrap; }
  .rv h3 { margin:4px 0 6px; }
  .rv details { border-top:1px solid var(--caravan-line); }
  .rv details .tiles { padding-bottom:8px; }
  .rv summary { display:flex; align-items:center; justify-content:space-between; gap:6px;
    list-style:none; font-size:13px; }
  .rv summary::-webkit-details-marker { display:none; }
  .rv summary span:first-child { flex:1; }
  .rv summary::after { content:""; width:6px; height:6px; margin:0 3px 3px;
    border:solid var(--rv-dim); border-width:0 1.5px 1.5px 0; transform:rotate(45deg); }
  .rv details[open]>summary::after { transform:rotate(225deg); margin-bottom:-3px; }
  .rv :is(button,select,summary,a):focus-visible { outline:2px solid var(--caravan-active); outline-offset:2px; }
  .rv .rv-switch { display:inline-flex; align-items:center; justify-content:flex-end; gap:7px; flex:none;
    min-width:72px; padding:0; background:transparent; border:0; }
  .rv .rv-switch b { position:relative; width:34px; height:20px; border-radius:14px; background:var(--rv-idle); }
  .rv .rv-switch b::after { content:""; position:absolute; width:14px; height:14px; left:3px; top:3px;
    border-radius:50%; background:var(--rv-knob); }
  .rv .rv-switch[aria-checked=true] b { background:var(--caravan-active); }
  .rv .rv-switch[aria-checked=true] b::after { left:17px; }
  .rv .rv-switch[aria-checked=mixed] b::after { left:10px; top:8px; height:4px; border-radius:3px; }
  .rv .rv-lamp { display:inline-grid; place-items:center; flex:none; width:27px; height:27px;
    border-radius:8px; background:var(--rv-inset); color:var(--rv-dim); }
  .rv .row[data-on=true] .rv-lamp { background:var(--rv-lamp-bg); color:var(--rv-lamp); }
  .rv .rv-level { border:0; max-width:74px; padding:0; background:none; color:var(--rv-dim); font-size:12px; }
  .rv .status { flex-basis:100%; }
  .rv .rv-step button { width:44px; background:none; border:0; font-size:20px; }
  .rv .rv-step strong { min-width:45px; text-align:center; }
  .rv p { margin:0 0 8px; }
  .rv .rv-metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(124px,100%),1fr));
    gap:8px 12px; padding:5px 0 12px; }
  .rv .rv-metrics strong,.rv .rv-metrics small { display:block; overflow-wrap:anywhere; }
  .rv .rv-bottles { border-top:1px solid var(--caravan-line); padding-top:9px; }
  .rv .rv-bottles .rv-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .rv .rv-bottles h4 { margin:0; }
  .rv [hidden] { display:none!important; }
  @media (max-width:380px) { .rv ha-card { padding-inline:9px; } .rv .label,.rv .controls { gap:4px; } }
`;

class AdriaCard extends HTMLElement {
  static getStubConfig(hass) {
    const ids = deviceIds(hass);
    return ids.length === 1 ? { device: ids[0] } : {};
  }

  static getConfigElement() {
    return element("adria-mach-card-editor");
  }

  getCardSize() { return this.constructor.kind === "lights" ? 4 : 5; }
  getGridOptions() { return { columns: 12, rows: "auto", min_columns: 6 }; }

  setConfig(config) {
    this.config = config;
    this.signature = undefined;
    this.refresh();
  }

  set hass(hass) {
    this.home = hass;
    this.refresh();
  }

  t(key) { return label(this.home, WORDS[key]); }
  id(domain, key) { return this.entityScope.matches.get(`${domain}:${key}`); }

  refresh() {
    if (!this.config || !this.home?.states) return;
    const entities = this.home.entities;
    if (entities !== this.registry) {
      this.registry = entities;
      this.signature = undefined;
    }
    if (this.signature === undefined || this.language !== finnish(this.home)) {
      this.language = finnish(this.home);
      this.entityScope = scope(this.home, this.config.device);
      this.signature = this.entityScope.device ?? null;
      this.build();
    }
    const layout = this.shadowRoot.querySelector(".caravan");
    if (layout) layout.style.colorScheme = this.home.themes?.darkMode ? "dark" : "light";
    for (const update of this.bindings) update();
  }

  section(parent, title, symbol, wide = false) {
    const card = element("ha-card");
    if (wide) card.className = "wide";
    if (title) {
      const heading = element("h3");
      heading.append(icon(symbol), title);
      card.append(heading);
    }
    parent.append(card);
    return card;
  }

  build() {
    const shadow = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    this.bindings = [];
    const privateView = this.constructor.kind === "caravan";
    const revised = privateView && this.config.layout_revision === 2;
    const layout = element("div", undefined, { className: privateView ? "layout caravan" : "layout" });
    if (revised) layout.classList.add("rv");
    shadow.replaceChildren(element("style", revised ? STYLE + CARAVAN_STYLE : STYLE), layout);
    if (!this.entityScope.device || !this.entityScope.matches.size ||
        (privateView && this.config.installation_device !== this.entityScope.device)) {
      this.section(layout).append(element("div", this.t("choose")));
      return;
    }
    if (revised) {
      this.caravan(layout);
    } else if (privateView) {
      layout.append(element("h2", this.config.title ?? "Vaunu", { className: "wide" }));
      this.overview(layout, true);
      this.heating(layout, true);
      this.lights(layout, true);
      this.energy(layout, true);
    } else {
      this[this.constructor.kind](layout, false);
    }
  }

  reading(id, key, symbol, hero = false, formatter) {
    if (!id) return null;
    const row = element("div", undefined, { className: hero ? "" : "row" });
    const text = element("span", undefined, { className: "label" });
    if (symbol) text.append(icon(symbol));
    text.append(this.t(key));
    const value = element("strong", "—", { className: hero ? "hero" : "" });
    row.append(text, value);
    this.bindings.push(() => {
      const state = this.home.states[id];
      value.textContent = usable(state)
        ? (formatter?.(state) ?? this.home.formatEntityState(state))
        : "—";
    });
    return row;
  }

  addReading(parent, ...args) {
    const reading = this.reading(...args);
    if (reading) parent.append(reading);
  }

  tile(parent, id, options = {}) {
    if (!id) return;
    this.native(parent, { type: "tile", entity: id, tap_action: { action: "more-info" }, ...options });
  }

  native(parent, config, enabled = () => true) {
    const host = element("div");
    parent.append(host);
    let card;
    let loading = false;
    const update = () => {
      if (card) {
        card.hass = this.home;
      } else if (!loading && enabled()) {
        loading = true;
        window.loadCardHelpers().then(async (helpers) => {
          if (host.getRootNode() !== this.shadowRoot) return;
          card = await helpers.createCardElement(config);
          if (host.getRootNode() !== this.shadowRoot) return;
          card.hass = this.home;
          host.replaceChildren(card);
        }).catch(() => {
          if (host.getRootNode() === this.shadowRoot) host.textContent = this.t("unavailable");
        });
      }
    };
    this.bindings.push(update);
    return update;
  }

  overview(parent, privateView) {
    const card = this.section(parent, privateView ? null : label(this.home, PICKER.overview), "mdi:caravan", true);
    const temperatures = element("div", undefined, { className: "temps" });
    this.addReading(temperatures, this.id("sensor", "living_temperature"), "inside", "mdi:thermometer", true);
    this.addReading(temperatures, this.id("sensor", "outside_temperature"), "outside", "mdi:thermometer-low", true);
    card.append(temperatures);
    const connection = element("div", undefined, { className: "summary-pair" });
    this.addReading(connection, this.id("sensor", "connection_state"), "linked", "mdi:connection");
    this.addReading(connection, this.id("sensor", "last_snapshot_age"), "age", "mdi:clock-outline");
    card.append(connection);
    if (privateView) {
      const fridge = element("div", undefined, { className: "summary-pair" });
      this.tile(fridge, this.id("switch", "fridge_power"), {
        name: this.t("fridge"), features: [{ type: "toggle" }], features_position: "inline",
      });
      this.addReading(fridge, this.id("select", "fridge_source"), "source", "mdi:refrigerator-outline");
      const power = element("div", undefined, { className: "summary-pair" });
      this.addReading(power, this.id("binary_sensor", "mains_supply"), "mains", "mdi:power-plug-outline");
      this.addReading(power, this.id("sensor", "battery_voltage"), "battery", "mdi:car-battery");
      const water = element("div", undefined, { className: "summary-pair" });
      this.addReading(water, this.id("sensor", "fresh_water_level"), "fresh", "mdi:water-outline");
      this.addReading(water, this.id("sensor", "waste_water_level"), "waste", "mdi:water-off-outline");
      card.append(fridge, power, water);
    } else {
      this.addReading(card, this.id("binary_sensor", "mains_supply"), "mains", "mdi:power-plug-outline");
    }
    if (this.config.show_map && !privateView) this.location(card);
  }

  heating(parent, privateView) {
    const card = this.section(parent, label(this.home, PICKER.heating), "mdi:thermometer");
    const tiles = element("div", undefined, { className: "tiles" });
    card.append(tiles);
    this.tile(tiles, this.id("climate", "heating_climate"), {
      features: [
        { type: "target-temperature" },
        { type: "climate-hvac-modes", hvac_modes: ["heat", "off"] },
      ],
    });
    this.tile(tiles, this.id("select", "heating_source"), {
      name: this.t("source"), features: [{ type: "select-options" }],
    });
    if (privateView) {
      this.tile(tiles, this.id("select", "heating_priority"), {
        name: this.t("priority"), features: [{ type: "select-options" }],
      });
    }
    if (privateView && this.config.spot_control?.startsWith("input_boolean.")) {
      this.tile(tiles, this.config.spot_control, {
        name: this.t("spot"), features: [{ type: "toggle" }], features_position: "inline",
      });
    }
    this.tile(tiles, this.id("water_heater", "water_heater_control"), {
      features: [{ type: "water-heater-operation-modes" }],
    });
  }

  lights(parent, privateView) {
    const card = this.section(parent, label(this.home, PICKER.lights), "mdi:lightbulb-outline");
    const status = element("div", undefined, { className: "hint status" });
    status.setAttribute("role", "status");
    const actions = element("div", undefined, { className: "actions" });
    card.append(actions, status);
    const lookup = (domain, key) => this.id(domain, key);
    for (const [combined, key, symbol] of [
      [false, "insideOff", "mdi:lightbulb-off-outline"],
      [true, "allOff", "mdi:power"],
    ]) {
      const steps = shutdownSteps(lookup, combined, this.config.include_aux === true);
      if (!steps.length || (combined && privateView && !this.id("light", "outside_light"))) continue;
      const button = element("button", undefined, { type: "button" });
      button.append(icon(symbol), " ", this.t(key));
      actions.append(button);
      this.bindings.push(() => {
        const running = combined && privateView &&
          this.home.states[this.config.shutdown_script]?.state !== "off";
        button.disabled = Boolean(this.sending) || running || steps.some(([domain, , id]) => {
          const state = this.home.states[id];
          return !usable(state, domain === "button") || state.attributes.request_pending;
        });
      });
      button.addEventListener("click", () => this.shutdown(steps, combined, privateView, status));
    }
    this.lightRow(card, "light", "outside_light");
    this.lightRow(card, "light", "light_master");
    const details = element("details");
    details.append(element("summary", this.t("groups")));
    for (const key of LIGHT_KEYS) this.lightRow(details, "light", key);
    if (this.config.include_aux === true) this.lightRow(details, "switch", "aux_output");
    if (details.childElementCount > 1) {
      if (!privateView) details.open = true;
      card.append(details);
    }
  }

  lightRow(parent, domain, key) {
    const id = this.id(domain, key);
    if (!id) return;
    const row = element("div", undefined, { className: "row" });
    const rowLabel = element("span", undefined, { className: "label" });
    const alias = this.config.light_labels?.[key];
    const name = alias?.name?.trim() || entityName(this.home, id);
    const symbol = alias?.icon || this.home.entities[id]?.icon
      || (key === "outside_light" ? "mdi:outdoor-lamp" : "mdi:lightbulb-outline");
    rowLabel.append(icon(symbol), name);
    const controls = element("div", undefined, { className: "controls" });
    const power = element("button", "—", { type: "button" });
    const brightness = element("select");
    brightness.setAttribute("aria-label", `${name}, ${this.t("brightness")}`);
    const current = new Option(this.t("brightness"), "");
    current.disabled = true;
    brightness.add(current);
    for (const value of PRESETS) brightness.add(new Option(`${value} %`, String(value)));
    const feedback = element("span", undefined, { className: "hint status" });
    feedback.setAttribute("role", "status");
    controls.append(brightness, power);
    row.append(rowLabel, controls, feedback);
    parent.append(row);

    const observed = () => {
      const state = this.home.states[id];
      const attrs = state?.attributes ?? {};
      return { state, attrs, on: (attrs.reported_state ?? state?.state) === "on" };
    };
    this.bindings.push(() => {
      const { state, attrs, on } = observed();
      const available = usable(state);
      const busy = Boolean(this.sending) || Boolean(attrs.request_pending);
      const dimmer = domain === "light" && attrs.supported_color_modes?.includes("brightness");
      brightness.hidden = !dimmer;
      brightness.disabled = !available || busy;
      if (this.shadowRoot.activeElement !== brightness || busy) {
        const raw = attrs.reported_brightness ?? (attrs.request_pending ? null : attrs.brightness);
        const percent = on && Number.isFinite(raw) ? Math.round(raw * 100 / 255) : null;
        current.textContent = percent == null ? this.t("brightness") : `${percent} %`;
        brightness.value = PRESETS.includes(percent) ? String(percent) : "";
      }
      power.disabled = !available || busy;
      power.textContent = available ? (on ? "OFF" : "ON") : "—";
      power.classList.toggle("active", available && on);
      power.setAttribute("aria-label", `${name}, ${this.t(available ? (on ? "turnOff" : "turnOn") : "unavailable")}`);
      if (attrs.request_pending) feedback.textContent = this.t("pending");
      else if (!available) feedback.textContent = this.t("unavailable");
      else if ([this.t("pending"), this.t("unavailable")].includes(feedback.textContent)
               && !this.sending) feedback.textContent = "";
    });
    power.addEventListener("click", () => {
      if (power.disabled) return;
      const service = observed().on ? "turn_off" : "turn_on";
      this.send(domain, service, id, {}, feedback);
    });
    brightness.addEventListener("change", () => {
      const level = Number(brightness.value);
      if (brightness.disabled || !PRESETS.includes(level)) return;
      this.send("light", "turn_on", id, { brightness_pct: level }, feedback);
    });
  }

  async send(domain, service, id, data, feedback) {
    if (this.sending) return;
    this.sending = true;
    feedback.textContent = this.t("pending");
    this.refresh();
    try {
      await this.home.callService(domain, service, data, { entity_id: id });
      feedback.textContent = "";
    } catch {
      feedback.textContent = this.t("failed");
    } finally {
      this.sending = false;
      this.refresh();
    }
  }

  async shutdown(steps, combined, privateView, feedback) {
    if (this.sending) return;
    this.sending = true;
    feedback.textContent = this.t("pending");
    this.refresh();
    let completed = 0;
    const script = combined && privateView && this.config.shutdown_script;
    try {
      if (steps.some(([domain, , id]) => !usable(this.home.states[id], domain === "button"))) {
        throw new Error("unavailable");
      }
      if (combined && privateView) {
        if (this.config.installation_device !== this.entityScope.device ||
            !/^script\.[a-z0-9_]+$/.test(script || "") ||
            this.home.states[script]?.state !== "off") throw new Error("invalid installation");
        await this.home.callService("script", script.slice(7), {});
      } else {
        for (const [domain, service, id] of steps) {
          const state = this.home.states[id];
          if (!usable(state, domain === "button") || state.attributes.request_pending) {
            throw new Error("unavailable");
          }
          await this.home.callService(domain, service, {}, { entity_id: id });
          completed++;
        }
      }
      feedback.textContent = this.t("done");
    } catch {
      feedback.textContent = this.t(combined && (completed || script) ? "partial" : "failed");
    } finally {
      this.sending = false;
      this.refresh();
    }
  }

  caravan(layout) {
    const header = element("header", undefined, { className: "wide" });
    const title = element("h2");
    title.append(icon("mdi:caravan"), this.config.title ?? "Vaunu");
    const line = element("p", undefined, { className: "hint" });
    const dot = element("span", undefined, { className: "rv-dot" });
    const connection = element("span");
    line.append(dot, connection);
    header.append(title, line);
    layout.append(header);
    this.bindings.push(() => {
      const state = this.home.states[this.id("sensor", "connection_state")];
      const age = this.home.states[this.id("sensor", "last_snapshot_age")];
      dot.classList.toggle("ok", state?.state === "ready");
      connection.textContent = [this.t("linked"), this.display(state), this.t("age"), this.display(age)].join(" · ");
    });

    this.caravanHeating(layout);
    this.caravanLights(layout);
    this.caravanSupplies(layout);
  }

  display(state) {
    return usable(state) ? this.home.formatEntityState(state) : "—";
  }

  number(value, digits = 2) {
    return new Intl.NumberFormat(this.language ? "fi" : "en", { maximumFractionDigits: digits }).format(value);
  }

  disclosure(parent, title) {
    const details = element("details");
    const summary = element("summary");
    summary.append(element("span", title));
    details.append(summary);
    parent.append(details);
    return details;
  }

  powerControl(name, role = "switch") {
    const control = element("button", undefined, { type: "button", className: "rv-switch" });
    control.setAttribute("role", role);
    control.setAttribute("aria-label", name);
    const thumb = element("b");
    thumb.setAttribute("aria-hidden", "true");
    control.append(element("span", "—", { className: "hint" }), thumb);
    return control;
  }

  paintPower(button, state, disabled, pending) {
    button.setAttribute("aria-checked", state === "mixed" ? "mixed" : String(state === "on"));
    button.disabled = disabled;
    button.firstElementChild.textContent = pending ? this.t("pending") :
      state === "mixed" ? this.t("someOn") :
      state ? this.t(state) : this.t("unavailable");
  }

  caravanPowerRow(parent, id, name, { symbol, dimmer = false, climate = false, heading = false } = {}) {
    if (!id) return;
    const domain = id.split(".")[0];
    const state = () => this.home.states[id];
    const observed = () => climate
      ? ({ heat: "on", off: "off" })[state()?.state] ?? null
      : reportedPower(state());
    const row = element("div", undefined, { className: "row" });
    const title = element(heading ? "h3" : "span", undefined, { className: "label" });
    if (symbol) {
      const lamp = element("span", undefined, { className: heading ? "" : "rv-lamp" });
      lamp.append(icon(symbol));
      title.append(lamp);
    }
    title.append(name);
    const power = this.powerControl(name);
    const controls = element("div", undefined, { className: "controls" });
    const feedback = element("span", undefined, { className: "hint status" });
    feedback.setAttribute("role", "status");
    this.bindings.push(() => {
      const pending = Boolean(state()?.attributes.request_pending);
      const value = observed();
      row.dataset.on = String(value === "on");
      this.paintPower(power, value, !value || this.sending || !readyToControl(state()), pending);
    });
    if (dimmer) {
      const brightness = element("select", undefined, { className: "rv-level" });
      brightness.setAttribute("aria-label", `${name}, ${this.t("brightness")}`);
      const current = new Option(this.t("brightness"), "");
      current.disabled = true;
      brightness.add(current);
      for (const preset of PRESETS) brightness.add(new Option(`${preset} %`, String(preset)));
      controls.append(brightness);
      this.bindings.push(() => {
        const attrs = state()?.attributes ?? {};
        brightness.hidden = !attrs.supported_color_modes?.includes("brightness");
        brightness.disabled = power.disabled;
        if (this.shadowRoot.activeElement === brightness && !brightness.disabled) return;
        const raw = attrs.reported_brightness ?? (attrs.request_pending ? null : attrs.brightness);
        const percent = observed() === "on" && Number.isFinite(raw) ? Math.round(raw * 100 / 255) : null;
        current.textContent = percent === null ? this.t("brightness") : `${percent} %`;
        brightness.value = PRESETS.includes(percent) ? String(percent) : "";
      });
      brightness.addEventListener("change", () => {
        const level = Number(brightness.value);
        if (!brightness.hidden && !power.disabled && PRESETS.includes(level)) {
          this.send("light", "turn_on", id, { brightness_pct: level }, feedback);
        }
      });
    }
    controls.append(power);
    row.append(title, controls, feedback);
    parent.append(row);
    power.addEventListener("click", () => {
      if (!power.disabled && readyToControl(state())) {
        this.send(domain, observed() === "on" ? "turn_off" : "turn_on", id, {}, feedback);
      }
    });
  }

  caravanHeating(parent) {
    const card = this.section(parent);
    const temperatures = element("div", undefined, { className: "temps" });
    this.addReading(temperatures, this.id("sensor", "living_temperature"), "inside", null, true);
    this.addReading(temperatures, this.id("sensor", "outside_temperature"), "outside", null, true);
    card.append(temperatures);
    const climate = this.id("climate", "heating_climate");
    this.caravanPowerRow(card, climate, label(this.home, PICKER.heating), {
      symbol: "mdi:thermometer", climate: true, heading: true,
    });
    if (climate) this.caravanTarget(card, climate);
    const details = this.disclosure(card, this.t("heatSettings"));
    const spot = this.config.spot_control;
    if (/^input_boolean\.[a-z0-9_]+$/.test(spot ?? "")) {
      const summaryState = element("small");
      details.firstElementChild.append(summaryState);
      this.bindings.push(() => {
        summaryState.textContent = this.home.states[spot]?.state === "on"
          ? label(this.home, ["Spot control on", "Pörssisähkö päällä"])
          : this.home.states[spot]?.state === "off"
            ? label(this.home, ["Spot control off", "Pörssisähkö pois"]) : "";
      });
      this.caravanPowerRow(details, spot, this.t("spot"));
      this.caravanPrice(details);
    }
    const tiles = element("div", undefined, { className: "tiles" });
    details.append(tiles);
    this.tile(tiles, this.id("select", "heating_source"), {
      name: this.t("source"), features: [{ type: "select-options" }],
    });
    this.tile(tiles, this.id("select", "heating_priority"), {
      name: this.t("priority"), features: [{ type: "select-options" }],
    });
    this.tile(tiles, this.id("water_heater", "water_heater_control"), {
      name: this.t("hotWater"), features: [{ type: "water-heater-operation-modes" }],
    });
  }

  caravanTarget(parent, id) {
    const row = element("div", undefined, { className: "row" });
    const controls = element("div", undefined, { className: "controls rv-step" });
    const lower = element("button", "−", { type: "button" });
    const upper = element("button", "+", { type: "button" });
    lower.setAttribute("aria-label", label(this.home, ["Lower target", "Laske tavoitetta"]));
    upper.setAttribute("aria-label", label(this.home, ["Raise target", "Nosta tavoitetta"]));
    const value = element("strong", "—");
    const feedback = element("span", undefined, { className: "hint status" });
    feedback.setAttribute("role", "status");
    controls.append(lower, value, upper);
    row.append(element("span", this.t("target"), { className: "hint" }), controls, feedback);
    parent.append(row);
    const next = (direction) => {
      const state = this.home.states[id];
      const attrs = state?.attributes ?? {};
      if (!Number.isFinite(attrs.temperature)) return null;
      const target = attrs.temperature + direction * (attrs.target_temp_step ?? 1);
      return Number.isFinite(target) && target >= attrs.min_temp && target <= attrs.max_temp ? target : null;
    };
    const allowed = () => !this.sending && this.home.states[id]?.state === "heat"
      && this.home.states[this.id("binary_sensor", "mains_supply")]?.state === "on"
      && readyToControl(this.home.states[id]);
    for (const [button, direction] of [[lower, -1], [upper, 1]]) {
      button.addEventListener("click", () => {
        const temperature = next(direction);
        if (!button.disabled && allowed() && temperature !== null) {
          this.send("climate", "set_temperature", id, { temperature }, feedback);
        }
      });
      this.bindings.push(() => { button.disabled = !allowed() || next(direction) === null; });
    }
    this.bindings.push(() => {
      const state = this.home.states[id];
      const temperature = state?.attributes.temperature;
      value.textContent = usable(state) && Number.isFinite(temperature)
        ? `${this.number(temperature)} ${this.home.config?.unit_system?.temperature ?? "°C"}` : "—";
    });
  }

  caravanLights(parent) {
    const card = this.section(parent, label(this.home, PICKER.lights), "mdi:lightbulb-outline");
    const includeRear = this.config.include_aux === true;
    const light = (container, key, domain = "light") => {
      const id = this.id(domain, key);
      if (!id) return;
      const alias = this.config.light_labels?.[key];
      const name = alias?.name?.trim() || (key === "light_master" ? this.t("interior") : entityName(this.home, id));
      const symbol = alias?.icon || this.home.entities[id]?.icon
        || (key === "outside_light" ? "mdi:outdoor-lamp" : "mdi:lightbulb-outline");
      this.caravanPowerRow(container, id, name, { symbol, dimmer: domain === "light" });
    };
    light(card, "light_master");
    this.caravanCombined(card);
    light(card, "outside_light");
    if (LIGHT_KEYS.some(key => this.id("light", key)) || (includeRear && this.id("switch", "aux_output"))) {
      const details = this.disclosure(card, includeRear ? this.t("lightGroups") : this.t("groups"));
      for (const key of LIGHT_KEYS) light(details, key);
      if (includeRear) light(details, "aux_output", "switch");
    }
  }

  caravanCombined(parent) {
    const name = this.t("allLights");
    const control = this.powerControl(name, "checkbox");
    const scope = element("span", name);
    const action = element("small");
    control.setAttribute("aria-describedby", "rv-combined-action");
    action.id = "rv-combined-action";
    action.style.display = "block";
    scope.append(action);
    const lamp = element("span", undefined, { className: "rv-lamp" });
    lamp.append(icon("mdi:lightbulb-group-outline"));
    const title = element("span", undefined, { className: "label" });
    title.append(lamp, scope);
    const row = element("div", undefined, { className: "row" });
    const feedback = element("span", undefined, { className: "hint status" });
    feedback.setAttribute("role", "status");
    row.append(title, control, feedback);
    parent.append(row);

    const members = [
      ["light", this.id("light", "light_master")],
      ["light", this.id("light", "outside_light")],
    ];
    const includeRear = this.config.include_aux === true;
    if (includeRear) members.push(["switch", this.id("switch", "aux_output")]);
    const offButton = this.id("button", "all_lights_off");
    const script = this.config.shutdown_script;
    const device = this.entityScope.device;
    const config = this.config;
    const sameScope = () => this.config === config && this.entityScope.device === device &&
      this.shadowRoot.contains(row);
    const observed = () => {
      const states = members.map(([,id]) => reportedPower(this.home.states[id]));
      if (states.includes(null)) return null;
      return states.every(state => state === states[0]) ? states[0] : "mixed";
    };
    const ready = (allowResync = true) => sameScope()
      && /^script\.[a-z0-9_]+$/.test(script ?? "")
      && this.home.states[script]?.state === "off"
      && readyToControl(this.home.states[offButton], true, allowResync)
      && members.every(([,id]) => readyToControl(this.home.states[id], false, allowResync));
    this.bindings.push(() => {
      const state = observed();
      const pending = members.some(([,id]) => this.home.states[id]?.attributes.request_pending)
        || this.home.states[script]?.state === "on";
      this.paintPower(control, state, !state || this.sending || !ready(), pending);
      row.dataset.on = String(state === "on");
      action.textContent = state === "mixed" ? this.t("tapOff") : "";
    });
    control.addEventListener("click", async () => {
      const state = observed();
      if (control.disabled || this.sending || !state || !ready()) return;
      if (state !== "off") {
        // Keep the installed script as the single owner of combined shutdown.
        await this.shutdown(shutdownSteps((domain, key) => this.id(domain, key), true, includeRear),
          true, true, feedback);
        return;
      }
      this.sending = true;
      feedback.textContent = this.t("pending");
      this.refresh();
      let attempted = false;
      try {
        for (const [domain, id] of members) {
          if (!ready(!attempted) || !reportedPower(this.home.states[id])) throw new Error("unavailable");
          attempted = true;
          await this.home.callService(domain, "turn_on", {}, { entity_id: id });
          const reported = await this.home.callApi("GET", `states/${id}`);
          if (reportedPower(reported) !== "on") throw new Error("unconfirmed");
        }
        feedback.textContent = this.t("done");
      } catch {
        feedback.textContent = attempted
          ? label(this.home, ["Lighting operation interrupted. Check the reported lights.",
            "Valojen ohjaus keskeytyi. Tarkista valojen ilmoitettu tila."])
          : this.t("failed");
      } finally {
        this.sending = false;
        this.refresh();
      }
    });
  }

  caravanPrice(parent) {
    const config = this.config.spot_price;
    if (!config || !Number.isFinite(config.tax_multiplier) || config.tax_multiplier <= 0) return;
    const cents = (price) => this.number(price * 100 * config.tax_multiplier);
    const row = element("div", undefined, { className: "row" });
    const price = element("strong", "—");
    row.append(element("span", this.t("price")), price);
    parent.append(row);
    this.bindings.push(() => {
      const current = measured(this.external(config.entity, "sensor"), "EUR/kWh");
      price.textContent = current === null ? "—" : `${cents(current)} ${this.language ? "snt" : "¢"}/kWh`;
    });
    if (![config.below, config.above, config.warm_target, config.cool_target].every(Number.isFinite)
      || config.below >= config.above) return;
    const low = cents(config.below);
    const high = cents(config.above);
    const warm = this.number(config.warm_target);
    const cool = this.number(config.cool_target);
    parent.append(element("p", label(this.home, [
      `At home on shore power, with heating and spot control on and the connection ready, the rule requests ${warm} °C below ${low} ¢/kWh and ${cool} °C above ${high} ¢/kWh. Between these prices it holds the current target.`,
      `Kotona verkkovirrassa sekä lämmityksen ja pörssiohjauksen ollessa päällä ohjaus pyytää ${warm} °C alle ${low} snt/kWh hinnalla ja ${cool} °C yli ${high} snt/kWh hinnalla, kun yhteys on valmis. Välillä ${low}–${high} snt/kWh tavoite säilyy.`,
    ]), { className: "hint" }));
  }

  external(id, domain) {
    return typeof id === "string" && id.startsWith(`${domain}.`) ? this.home.states[id] : undefined;
  }

  metric(parent, title, display) {
    const item = element("div");
    const value = element("strong", "—");
    item.append(element("small", title), value);
    parent.append(item);
    this.bindings.push(() => { value.textContent = display() ?? "—"; });
    return item;
  }

  caravanSupplies(parent) {
    const card = this.section(parent, this.t("supplies"), "mdi:power-plug-outline", true);
    const summary = element("div", undefined, { className: "rv-metrics" });
    card.append(summary);
    const read = (domain, key) => this.home.states[this.id(domain, key)];
    this.metric(summary, this.t("mains"), () => {
      const state = read("binary_sensor", "mains_supply")?.state;
      if (state === "on") return label(this.home, ["230 V connected", "230 V kytketty"]);
      if (state === "off") return label(this.home, ["Disconnected", "Irti"]);
      return null;
    });
    const battery = this.config.battery ?? {};
    const bms = key => this.external(battery[key], "sensor");
    if (battery.charge) {
      const item = this.metric(summary, this.t("charge"), () => this.display(bms("charge")));
      const detail = element("small");
      item.append(detail);
      this.bindings.push(() => {
        const power = measured(bms("power"), "W");
        const charging = this.external(battery.charging, "binary_sensor")?.state;
        const direction = power > 0 && charging === "on" ? "charging"
          : power < 0 && charging === "off" ? "discharging"
            : power === 0 && charging === "off" ? "idleBattery" : null;
        detail.textContent = power === null ? "" :
          [`${this.number(direction ? Math.abs(power) : power, 1)} W`, direction && this.t(direction)].filter(Boolean).join(" · ");
      });
    } else {
      this.metric(summary, this.t("battery"), () => this.display(read("sensor", "battery_voltage")));
    }
    this.metric(summary, this.t("fresh"), () => this.display(read("sensor", "fresh_water_level")));
    this.metric(summary, this.t("waste"), () => this.display(read("sensor", "waste_water_level")));
    this.caravanGas(card);
    if (battery.charge) this.caravanBattery(card, bms, battery.charging);

    const devices = this.disclosure(card, this.t("appliances"));
    devices.firstElementChild.append(element("small", `${this.t("fridge")}, ${this.t("pump").toLowerCase()}`));
    this.caravanPowerRow(devices, this.id("switch", "fridge_power"), this.t("fridge"));
    this.tile(devices, this.id("select", "fridge_source"), {
      name: this.t("source"), features: [{ type: "select-options" }],
    });
    this.tile(devices, this.id("select", "fridge_level"), {
      name: this.t("fridgeLevel"), features: [{ type: "select-options" }],
    });
    this.caravanPowerRow(devices, this.id("switch", "fridge_auto"), this.t("fridgeAuto"));
    this.caravanPowerRow(devices, this.id("switch", "water_pump"), this.t("pump"));
    if (this.config.show_map) this.location(card);
    this.caravanLevelling(card);
    const dimensions = [
      ["length", "vehicle_length_with_towbar"], ["width", "vehicle_width"], ["height", "vehicle_height"],
    ].filter(([,key]) => this.id("sensor", key));
    if (dimensions.length) {
      const details = this.disclosure(card, this.t("dimensions"));
      const grid = element("div", undefined, { className: "rv-metrics" });
      details.append(grid);
      for (const [labelKey, key] of dimensions) {
        this.metric(grid, this.t(labelKey), () => {
          const value = measured(read("sensor", key), "mm");
          return value === null ? null : `${this.number(value / 1000, 3)} m`;
        });
      }
    }
  }

  caravanBattery(parent, bms, chargingId) {
    const details = this.disclosure(parent, this.t("batteryDetails"));
    details.firstElementChild.append(element("small", "Bluetooth BMS"));
    const grid = element("div", undefined, { className: "rv-metrics" });
    details.append(grid);
    for (const [key, title] of [
      ["capacity", "designCapacity"], ["voltage", "voltage"], ["current", "current"],
      ["temperature", "batteryTemperature"],
    ]) this.metric(grid, this.t(title), () => this.display(bms(key)));
    this.metric(grid, this.t("storedEnergy"), () => {
      const value = measured(bms("energy"), "Wh");
      return value === null ? this.display(bms("energy")) : `${this.number(value / 1000)} kWh`;
    });
    const runtime = () => {
      const power = measured(bms("power"), "W");
      const state = bms("runtime");
      const unit = state?.attributes.unit_of_measurement;
      const duration = ["s", "min", "h", "d"].includes(unit) ? measured(state, unit) : null;
      const discharging = power !== null && power < 0
        && this.external(chargingId, "binary_sensor")?.state === "off";
      return discharging && duration !== null && duration >= 0 ? this.display(state) : null;
    };
    const item = this.metric(grid, this.t("runtime"), runtime);
    this.bindings.push(() => { item.hidden = runtime() === null; });
  }

  caravanGas(parent) {
    const bottles = this.config.gas_bottles;
    if (!Array.isArray(bottles) || !bottles.length) return;
    const section = element("div", undefined, { className: "rv-bottles" });
    const grid = element("div", undefined, { className: "rv-metrics" });
    section.append(element("h4", this.t("cylinders")), grid);
    parent.append(section);
    const flag = id => this.external(id, "binary_sensor")?.state;
    const bothCalibrating = () => bottles.length === 2 && bottles.every(bottle => flag(bottle.calibration) === "on");
    for (const bottle of bottles) {
      const amount = () => [
        this.external(bottle.level, "sensor"), this.external(bottle.remaining, "sensor"),
      ].filter((state, index) => measured(state, index === 0 ? "%" : "kg") !== null);
      const item = this.metric(grid, bottle.name ?? this.t("gas"), () => {
        const states = amount();
        return states.length ? states.map(state => this.display(state)).join(" · ") : this.t("gasMissing");
      });
      const details = element("small");
      item.append(details);
      this.bindings.push(() => {
        const status = [];
        const calibration = flag(bottle.calibration);
        const error = flag(bottle.error);
        if (calibration === "on" && !bothCalibrating()) status.push(this.t("calibrate"));
        if (error === "on") status.push(this.t("gasError"));
        if (flag(bottle.low) === "on") status.push(this.t("lowGas"));
        const until = Date.parse(this.external(bottle.empty, "sensor")?.state);
        if (calibration === "off" && error === "off" && until > Date.now() && amount().length === 2) {
          const date = new Intl.DateTimeFormat(this.language ? "fi" : "en", { dateStyle: "medium", timeStyle: "short" });
          status.push(`${this.t("gasEstimate")} · ${date.format(until)}`);
        }
        details.textContent = status.join(" · ");
      });
    }
    const note = element("p", label(this.home, ["Both sensors request calibration.", "Molemmat anturit pyytävät kalibrointia." ]), { className: "hint" });
    section.append(note);
    this.bindings.push(() => { note.hidden = !bothCalibrating(); });
  }

  caravanLevelling(parent) {
    const path = this.config.levelling_path;
    if (!/^\/(?!\/)[a-z0-9/_-]+$/i.test(path ?? "")) return;
    const details = this.disclosure(parent, this.t("level"));
    const short = element("small");
    details.firstElementChild.append(short);
    const grid = element("div", undefined, { className: "rv-metrics" });
    details.append(grid, element("a", label(this.home, ["Open levelling", "Avaa tasausnäkymä"]), { href: path }));
    const config = this.config.levelling ?? {};
    const state = key => this.external(config[key], "sensor");
    const axes = ["lateral", "longitudinal"];
    for (const key of axes) this.metric(grid, this.t(key), () => this.display(state(key)));
    this.bindings.push(() => {
      const session = state("status");
      short.textContent = session?.state === "idle" ? this.t("notMeasuring") :
        usable(session) ? this.display(session) : "";
      const received = Date.parse(state("received")?.state);
      grid.hidden = session?.state !== "measuring" || !(received <= Date.now())
        || !(Date.parse(state("expires")?.state) > Date.now())
        || !axes.every(key => measured(state(key), "mm") !== null);
    });
  }

  energy(parent, privateView) {
    const card = this.section(parent, privateView ? null : label(this.home, PICKER.energy), "mdi:water-outline", privateView);
    const details = privateView ? element("details") : card;
    if (privateView) {
      details.append(element("summary", this.t("equipment")));
      card.append(details);
    } else {
      this.addReading(card, this.id("sensor", "fresh_water_level"), "fresh", "mdi:water-outline");
      this.addReading(card, this.id("sensor", "waste_water_level"), "waste", "mdi:water-off-outline");
      this.addReading(card, this.id("binary_sensor", "mains_supply"), "mains", "mdi:power-plug-outline");
      this.addReading(card, this.id("sensor", "battery_voltage"), "battery", "mdi:car-battery");
      this.tile(card, this.id("switch", "fridge_power"), {
        name: this.t("fridge"), features: [{ type: "toggle" }], features_position: "inline",
      });
    }
    this.addReading(details, this.id("sensor", "battery_current"), "battery", "mdi:current-dc");
    this.tile(details, this.id("switch", "water_pump"), {
      features: [{ type: "toggle" }], features_position: "inline",
    });
    this.tile(details, this.id("select", "fridge_source"), { features: [{ type: "select-options" }] });
    this.tile(details, this.id("select", "fridge_level"), { features: [{ type: "select-options" }] });
    this.tile(details, this.id("switch", "fridge_auto"), {
      features: [{ type: "toggle" }], features_position: "inline",
    });
    const gas = this.id("sensor", "gas_bottle_level");
    if (gas) this.addReading(details, gas, "gas", "mdi:gas-cylinder");
    else if (privateView) details.append(element("div", `${this.t("gas")} · ${this.t("noGas")}`, { className: "row hint" }));
    if (privateView && this.config.show_map) this.location(card);
    if (privateView && /^\/(?!\/)[a-z0-9/_-]+$/i.test(this.config.levelling_path ?? "")) {
      card.append(element("a", this.t("level"), { href: this.config.levelling_path }));
    }
  }

  location(parent) {
    const tracker = this.id("device_tracker", "location");
    if (!tracker) return;
    const details = element("details");
    details.append(element("summary", this.t("location")));
    const message = element("div", this.t("noLocation"), { className: "hint" });
    details.append(message);
    parent.append(details);
    const hasPosition = () => {
      const state = this.home.states[tracker];
      return usable(state) && Number.isFinite(state.attributes.latitude)
        && Number.isFinite(state.attributes.longitude);
    };
    const updateMap = this.native(
      details, { type: "map", entities: [tracker], hours_to_show: 0, aspect_ratio: "16:9" },
      () => details.open && hasPosition(),
    );
    const map = details.lastElementChild;
    const update = () => {
      message.hidden = hasPosition();
      map.hidden = !hasPosition();
      if (details.open && hasPosition()) updateMap();
    };
    details.addEventListener("toggle", update);
    this.bindings.push(update);
  }
}

class AdriaCardEditor extends HTMLElement {
  setConfig(config) {
    this.config = config;
    this.draw();
  }

  set hass(hass) {
    this.home = hass;
    const meta = deviceIds(hass).map((id) => [id, vehicleName(hass, id)]);
    const signature = JSON.stringify([meta, finnish(hass)]);
    if (this.signature === signature) return;
    this.signature = signature;
    this.draw();
  }

  edit(changes) {
    this.config = { ...this.config, ...changes };
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this.config }, bubbles: true, composed: true,
    }));
  }

  draw() {
    if (!this.config || !this.home) return;
    const t = (key) => label(this.home, WORDS[key]);
    const shadow = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    const container = element("div", undefined, { className: "editor" });
    const privateView = this.config.type === "custom:adria-mach-caravan";
    if (!privateView) {
      const devices = element("select");
      devices.add(new Option(t("choose"), ""));
      for (const id of deviceIds(this.home)) devices.add(new Option(vehicleName(this.home, id), id));
      devices.value = this.config.device ?? "";
      devices.addEventListener("change", () => {
        this.edit({ device: devices.value || undefined });
        this.draw();
      });
      const device = element("label", t("vehicle"));
      device.append(devices);
      container.append(device);
    }
    const lights = ["custom:adria-mach-lights", "custom:adria-mach-caravan"].includes(this.config.type);
    const checkbox = (key, title) => {
      const control = element("input", undefined, { type: "checkbox", checked: Boolean(this.config[key]) });
      const field = element("label", undefined, { className: "check" });
      field.append(control, t(title));
      control.addEventListener("change", () => this.edit({ [key]: control.checked }));
      container.append(field);
    };
    if (["custom:adria-mach-overview", "custom:adria-mach-caravan"].includes(this.config.type)) {
      checkbox("show_map", "gps");
    }
    if (lights) {
      if (!privateView) checkbox("include_aux", "includeAux");
      const details = element("details");
      details.append(element("summary", t("names")));
      const entries = scope(this.home, this.config.device).matches;
      for (const role of LIGHT_ROLES) {
        const id = entries.get(`${role === "aux_output" ? "switch" : "light"}:${role}`);
        if (!id) continue;
        const field = element("fieldset");
        field.append(element("legend", entityName(this.home, id)));
        for (const key of ["name", "icon"]) {
          const input = element("input", undefined, {
            value: this.config.light_labels?.[role]?.[key] ?? "",
            placeholder: key === "icon" ? "mdi:lightbulb-outline" : entityName(this.home, id),
          });
          input.addEventListener("change", () => {
            const aliases = this.config.light_labels ?? {};
            const item = { ...aliases[role], [key]: input.value.trim() };
            this.edit({ light_labels: { ...aliases, [role]: item } });
          });
          const fieldLabel = element("label", t(key));
          fieldLabel.append(input);
          field.append(fieldLabel);
        }
        details.append(field);
      }
      container.append(details);
    }
    shadow.replaceChildren(element("style", STYLE), container);
  }
}

customElements.define("adria-mach-card-editor", AdriaCardEditor);
for (const [kind, title] of Object.entries({ ...PICKER, caravan: ["Caravan", "Vaunu"] })) {
  const type = `adria-mach-${kind}`;
  customElements.define(type, class extends AdriaCard { static kind = kind; });
  if (kind !== "caravan") {
    window.customCards ??= [];
    window.customCards.push({
      type, name: `${BRAND} · ${label({ language: navigator.language }, title)}`,
      preview: true, documentationURL: "https://github.com/mimyll/adria-mach",
    });
  }
}
