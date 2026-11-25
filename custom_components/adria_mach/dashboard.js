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
    const layout = element("div", undefined, { className: privateView ? "layout caravan" : "layout" });
    shadow.replaceChildren(element("style", STYLE), layout);
    if (!this.entityScope.device || !this.entityScope.matches.size ||
        (privateView && this.config.installation_device !== this.entityScope.device)) {
      this.section(layout).append(element("div", this.t("choose")));
      return;
    }
    if (privateView) {
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
