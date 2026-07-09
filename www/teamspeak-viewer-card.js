/**
 * TeamSpeak Viewer Card - ein ts3.app/ts3manager-artiger Channel-Baum für
 * Home Assistant, gespeist aus der ha-teamspeak Integration.
 *
 * Konfiguration (minimal):
 *   type: custom:teamspeak-viewer-card
 *   channels_entity: sensor.teamspeak_<host>_kanale
 *   clients_entity: sensor.teamspeak_<host>_verbundene_clients
 *
 * Optional:
 *   title: Budenzauber
 *   status_entity: sensor.teamspeak_<host>_status
 *   max_clients_entity: sensor.teamspeak_<host>_maximale_clients
 *   show_spacers: true      # Spacer-Kanäle als Trenner rendern
 *   show_actions: true      # Klick-Aktionen (poke/move/kick/ban) aktivieren
 *   max_height: 480         # px, Baum scrollt darüber hinaus
 */
(function () {
  "use strict";

  const CARD_TYPE = "teamspeak-viewer-card";

  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
    );

  const countryFlag = (code) => {
    if (!code || code.length !== 2 || !/^[a-zA-Z]{2}$/.test(code)) return "";
    const base = 0x1f1e6;
    return String.fromCodePoint(
      ...[...code.toUpperCase()].map((ch) => base + ch.charCodeAt(0) - 65)
    );
  };

  const idleText = (seconds) => {
    if (!seconds || seconds < 60) return "";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
    return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
  };

  // "[cspacer]Text" -> {align: "c", text: "Text"}; kein Spacer -> null
  const parseSpacer = (name) => {
    const match = /^\[(l|r|c|\*)?spacer[^\]]*\](.*)$/i.exec(name || "");
    if (!match) return null;
    return { align: (match[1] || "l").toLowerCase(), text: match[2] || "" };
  };

  const clientPresence = (c) => {
    if (c.away) return { icon: "mdi:power-sleep", cls: "away", hint: "Abwesend" };
    if (c.output_muted || !c.output_hardware)
      return { icon: "mdi:headphones-off", cls: "muted", hint: "Ton aus" };
    if (c.input_muted || !c.input_hardware)
      return { icon: "mdi:microphone-off", cls: "muted", hint: "Mikro aus" };
    if (c.is_talking)
      return { icon: "mdi:account-voice", cls: "talking", hint: "Spricht" };
    return { icon: "mdi:account", cls: "online", hint: "Online" };
  };

  class TeamspeakViewerCard extends HTMLElement {
    static getStubConfig(hass) {
      const states = Object.values(hass?.states || {});
      const channels = states.find((s) => s.attributes?.channels);
      const clients = states.find((s) => s.attributes?.clients);
      return {
        channels_entity: channels?.entity_id || "sensor.teamspeak_kanale",
        clients_entity: clients?.entity_id || "sensor.teamspeak_verbundene_clients",
      };
    }

    setConfig(config) {
      if (!config.channels_entity || !config.clients_entity) {
        throw new Error(
          "channels_entity und clients_entity sind erforderlich " +
            "(Sensoren 'Kanäle' und 'Verbundene Clients' der TeamSpeak-Integration)"
        );
      }
      this._config = {
        show_spacers: true,
        show_actions: true,
        title: "TeamSpeak",
        ...config,
      };
      this._selectedClid = null;
      this._moveClid = null;
      this._signature = null;
    }

    set hass(hass) {
      this._hass = hass;
      const ch = hass.states[this._config.channels_entity];
      const cl = hass.states[this._config.clients_entity];
      const st = this._config.status_entity
        ? hass.states[this._config.status_entity]
        : null;
      const mx = this._config.max_clients_entity
        ? hass.states[this._config.max_clients_entity]
        : null;

      const signature = JSON.stringify([
        ch?.attributes?.channels,
        cl?.attributes?.clients,
        st?.state,
        mx?.state,
        this._selectedClid,
        this._moveClid,
      ]);
      if (signature === this._signature) return;
      this._signature = signature;
      this._render(ch, cl, st, mx);
    }

    getCardSize() {
      return 8;
    }

    _channels() {
      return (
        this._hass?.states[this._config.channels_entity]?.attributes?.channels || []
      );
    }

    _clients() {
      return (
        this._hass?.states[this._config.clients_entity]?.attributes?.clients || []
      );
    }

    _render(ch, cl, st, mx) {
      const channels = ch?.attributes?.channels || [];
      const clients = cl?.attributes?.clients || [];
      const status = st ? st.state : channels.length ? "online" : "unbekannt";
      const online = status === "online";
      const count = clients.length;
      const max = mx && !isNaN(Number(mx.state)) ? `/${mx.state}` : "";

      const byChannel = new Map();
      for (const client of clients) {
        if (!byChannel.has(client.cid)) byChannel.set(client.cid, []);
        byChannel.get(client.cid).push(client);
      }

      const depth = new Map();
      const rows = [];
      for (const channel of channels) {
        const d =
          channel.parent_id === 0 ? 0 : (depth.get(channel.parent_id) ?? 0) + 1;
        depth.set(channel.cid, d);
        rows.push(this._channelRow(channel, d));
        for (const client of byChannel.get(channel.cid) || []) {
          rows.push(this._clientRow(client, d + 1));
          if (this._selectedClid === client.clid && this._config.show_actions) {
            rows.push(this._actionBar(client, d + 1));
          }
        }
      }
      // Clients in Kanälen, die nicht in der Liste sind (sollte nicht passieren)
      for (const client of clients) {
        if (!depth.has(client.cid)) rows.push(this._clientRow(client, 0));
      }

      const moveBanner =
        this._moveClid !== null
          ? `<div class="banner">Zielkanal anklicken, um
               <b>${esc(this._clientName(this._moveClid))}</b> zu verschieben
               <button class="link" data-action="cancel-move">Abbrechen</button>
             </div>`
          : "";

      const maxHeight = this._config.max_height
        ? `max-height:${Number(this._config.max_height)}px;overflow-y:auto;`
        : "";

      this.innerHTML = `
        <ha-card>
          <style>
            ${CARD_TYPE} .head { display:flex; align-items:center; gap:10px;
              padding:14px 16px 8px; }
            ${CARD_TYPE} .dot { width:10px; height:10px; border-radius:50%;
              background: var(--error-color, #db4437); flex:none; }
            ${CARD_TYPE} .dot.on { background: var(--success-color, #43a047); }
            ${CARD_TYPE} .head .name { font-size:1.15em; font-weight:600; flex:1;
              overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            ${CARD_TYPE} .head .cnt { color: var(--secondary-text-color); }
            ${CARD_TYPE} .head ha-icon-button, ${CARD_TYPE} .head .hbtn {
              cursor:pointer; color: var(--secondary-text-color); border:none;
              background:none; padding:4px; }
            ${CARD_TYPE} .tree { padding: 4px 8px 12px; ${maxHeight} }
            ${CARD_TYPE} .row { display:flex; align-items:center; gap:8px;
              padding:3px 8px; border-radius:6px; min-height:26px; }
            ${CARD_TYPE} .row.ch { color: var(--primary-text-color); font-weight:500; }
            ${CARD_TYPE} .row.ch ha-icon { color: var(--secondary-text-color);
              --mdc-icon-size:18px; }
            ${CARD_TYPE} .row.cli { color: var(--primary-text-color); font-weight:400; }
            ${CARD_TYPE} .row.cli ha-icon { --mdc-icon-size:17px; }
            ${CARD_TYPE} .row .grow { flex:1; overflow:hidden;
              text-overflow:ellipsis; white-space:nowrap; }
            ${CARD_TYPE} .row .meta { color: var(--secondary-text-color);
              font-size:0.85em; flex:none; }
            ${CARD_TYPE} .row.cli:hover, ${CARD_TYPE} .row.ch.movetarget:hover {
              background: var(--secondary-background-color); cursor:pointer; }
            ${CARD_TYPE} .talking { color: var(--success-color, #43a047); }
            ${CARD_TYPE} .muted { color: var(--error-color, #db4437); }
            ${CARD_TYPE} .away { color: var(--warning-color, #ffa600); }
            ${CARD_TYPE} .online { color: var(--secondary-text-color); }
            ${CARD_TYPE} .badge { background: var(--secondary-background-color);
              border-radius:10px; padding:0 8px; font-size:0.8em;
              color: var(--secondary-text-color); flex:none; }
            ${CARD_TYPE} .spacer { color: var(--secondary-text-color);
              font-size:0.8em; padding:4px 8px; overflow:hidden;
              white-space:nowrap; letter-spacing:1px; }
            ${CARD_TYPE} .spacer.c { text-align:center; }
            ${CARD_TYPE} .spacer.r { text-align:right; }
            ${CARD_TYPE} .spacer.line { opacity:0.55; }
            ${CARD_TYPE} .actions { display:flex; gap:2px; flex-wrap:wrap;
              padding:2px 8px 6px; }
            ${CARD_TYPE} .actions button { display:flex; align-items:center; gap:4px;
              border:none; border-radius:6px; padding:4px 8px; cursor:pointer;
              background: var(--secondary-background-color);
              color: var(--primary-text-color); font: inherit; font-size:0.82em; }
            ${CARD_TYPE} .actions button:hover { filter: brightness(0.93); }
            ${CARD_TYPE} .actions button.danger { color: var(--error-color); }
            ${CARD_TYPE} .actions ha-icon { --mdc-icon-size:15px; }
            ${CARD_TYPE} .banner { margin:0 16px; padding:6px 10px;
              border-radius:8px; background: var(--secondary-background-color);
              font-size:0.9em; }
            ${CARD_TYPE} .banner .link { border:none; background:none;
              color: var(--primary-color); cursor:pointer; font:inherit; }
          </style>
          <div class="head">
            <span class="dot ${online ? "on" : ""}" title="${esc(status)}"></span>
            <span class="name">${esc(this._config.title)}</span>
            <span class="cnt">${count}${max} online</span>
            ${
              this._config.show_actions
                ? `<button class="hbtn" data-action="broadcast"
                     title="Rundnachricht an alle senden">
                     <ha-icon icon="mdi:bullhorn-outline"></ha-icon></button>`
                : ""
            }
          </div>
          ${moveBanner}
          <div class="tree">${rows.join("")}</div>
        </ha-card>`;

      this.onclick = (ev) => this._onClick(ev);
    }

    _channelRow(channel, depth) {
      const indent = `style="margin-left:${depth * 18}px"`;
      const spacer = parseSpacer(channel.name);
      if (spacer) {
        if (!this._config.show_spacers) return "";
        if (spacer.align === "*") {
          const line = spacer.text ? spacer.text.repeat(60).slice(0, 60) : "";
          return `<div class="spacer line">${esc(line)}</div>`;
        }
        return `<div class="spacer ${spacer.align}">${esc(spacer.text)}</div>`;
      }
      const count = channel.clients
        ? `<span class="badge">${channel.clients}</span>`
        : "";
      const lock = channel.has_password
        ? `<ha-icon icon="mdi:lock" style="--mdc-icon-size:14px"></ha-icon>`
        : "";
      const target = this._moveClid !== null ? "movetarget" : "";
      return `<div class="row ch ${target}" data-cid="${channel.cid}" ${indent}>
          <ha-icon icon="mdi:volume-high"></ha-icon>
          <span class="grow">${esc(channel.name)}</span>${lock}${count}
        </div>`;
    }

    _clientRow(client, depth) {
      const indent = `style="margin-left:${depth * 18}px"`;
      const presence = clientPresence(client);
      const flag = countryFlag(client.country);
      const idle = idleText(client.idle_seconds);
      const marks = [
        client.is_recording
          ? `<ha-icon class="muted" icon="mdi:record-rec" title="Nimmt auf"></ha-icon>`
          : "",
        client.is_channel_commander
          ? `<ha-icon class="talking" icon="mdi:star-outline" title="Channel-Commander"></ha-icon>`
          : "",
        client.is_priority_speaker
          ? `<ha-icon icon="mdi:account-star" title="Priority Speaker"></ha-icon>`
          : "",
      ].join("");
      return `<div class="row cli" data-clid="${client.clid}" ${indent}
          title="${esc(presence.hint)} · ${esc(client.platform)} ${esc(client.version)}">
          <ha-icon class="${presence.cls}" icon="${presence.icon}"></ha-icon>
          <span class="grow">${flag ? flag + " " : ""}${esc(client.nickname)}</span>
          ${marks}
          ${idle ? `<span class="meta">${idle}</span>` : ""}
        </div>`;
    }

    _actionBar(client, depth) {
      const indent = `style="margin-left:${depth * 18}px"`;
      const btn = (action, icon, label, danger = false) =>
        `<button class="${danger ? "danger" : ""}" data-action="${action}"
           data-clid="${client.clid}">
           <ha-icon icon="${icon}"></ha-icon>${label}</button>`;
      return `<div class="actions" ${indent}>
          ${btn("poke", "mdi:gesture-tap", "Anstupsen")}
          ${btn("msg", "mdi:message-text-outline", "Nachricht")}
          ${btn("move", "mdi:arrow-right-bold-box-outline", "Verschieben")}
          ${btn("kick-ch", "mdi:exit-run", "Kick (Kanal)", true)}
          ${btn("kick-sv", "mdi:karate", "Kick (Server)", true)}
          ${btn("ban", "mdi:gavel", "Bannen", true)}
        </div>`;
    }

    _clientName(clid) {
      const client = this._clients().find((c) => c.clid === clid);
      return client ? client.nickname : `clid ${clid}`;
    }

    _rerender() {
      this._signature = null;
      this.hass = this._hass;
    }

    async _call(service, data, okText) {
      try {
        await this._hass.callService("teamspeak", service, data);
        if (okText) this._toast(okText);
      } catch (err) {
        alert(`TeamSpeak: Aktion fehlgeschlagen\n${err.message || err}`);
      }
    }

    _toast(message) {
      this.dispatchEvent(
        new CustomEvent("hass-notification", {
          detail: { message },
          bubbles: true,
          composed: true,
        })
      );
    }

    _onClick(ev) {
      const actionEl = ev.target.closest("[data-action]");
      const row = ev.target.closest(".row");

      if (actionEl) {
        ev.stopPropagation();
        this._handleAction(actionEl.dataset.action, Number(actionEl.dataset.clid));
        return;
      }

      if (row?.dataset.cid !== undefined && this._moveClid !== null) {
        const cid = Number(row.dataset.cid);
        const name = this._clientName(this._moveClid);
        this._call(
          "move_client",
          { client_id: this._moveClid, channel_id: cid },
          `${name} verschoben`
        );
        this._moveClid = null;
        this._selectedClid = null;
        this._rerender();
        return;
      }

      if (row?.dataset.clid !== undefined && this._config.show_actions) {
        const clid = Number(row.dataset.clid);
        this._selectedClid = this._selectedClid === clid ? null : clid;
        this._rerender();
      }
    }

    _handleAction(action, clid) {
      const name = this._clientName(clid);
      switch (action) {
        case "cancel-move":
          this._moveClid = null;
          this._rerender();
          break;
        case "broadcast": {
          const message = prompt("Rundnachricht an alle:");
          if (message)
            this._call("broadcast_message", { message }, "Rundnachricht gesendet");
          break;
        }
        case "poke": {
          const message = prompt(`Anstupsen – Nachricht an ${name}:`);
          if (message)
            this._call("poke_client", { client_id: clid, message }, `${name} angestupst`);
          break;
        }
        case "msg": {
          const message = prompt(`Private Nachricht an ${name}:`);
          if (message)
            this._call("send_message", { client_id: clid, message }, "Nachricht gesendet");
          break;
        }
        case "move":
          this._moveClid = clid;
          this._rerender();
          break;
        case "kick-ch":
          if (confirm(`${name} aus dem Kanal kicken?`))
            this._call(
              "kick_client",
              { client_id: clid, scope: "channel" },
              `${name} gekickt (Kanal)`
            );
          break;
        case "kick-sv":
          if (confirm(`${name} vom Server kicken?`))
            this._call(
              "kick_client",
              { client_id: clid, scope: "server" },
              `${name} gekickt (Server)`
            );
          break;
        case "ban": {
          const input = prompt(
            `${name} bannen – Dauer in Sekunden (0 = dauerhaft):`,
            "3600"
          );
          if (input === null) break;
          const duration = Math.max(0, parseInt(input, 10) || 0);
          const label = duration ? `${duration} s` : "dauerhaft";
          if (confirm(`${name} wirklich bannen (${label})?`))
            this._call(
              "ban_client",
              { client_id: clid, duration },
              `${name} gebannt (${label})`
            );
          break;
        }
      }
    }
  }

  customElements.define(CARD_TYPE, TeamspeakViewerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TYPE,
    name: "TeamSpeak Viewer Card",
    description:
      "Channel-Baum mit Clients, Status-Icons und Verwaltungsaktionen (ha-teamspeak)",
  });
})();
