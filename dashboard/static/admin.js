"use strict";

const list = document.getElementById("operators");
const dialog = document.getElementById("operator-dialog");
const form = document.getElementById("operator-form");
const feedback = document.getElementById("feedback");
const csrf = document.getElementById("admin-data").dataset.csrf;
let operators = [];
let editing = null;

function showFeedback(message, error = false) {
    feedback.textContent = message;
    feedback.className = error ? "error" : "success";
}

function render() {
    list.replaceChildren();
    if (!operators.length) {
        const empty = document.createElement("p");
        empty.textContent = "No configured operators.";
        list.append(empty);
    }
    for (const item of operators) {
        const row = document.createElement("article");
        row.className = "operator";
        const details = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = item.callsign;
        const status = document.createElement("small");
        status.className = item.active ? "status-active" : "status-disabled";
        status.textContent = item.active ? "Active" : "Disabled";
        details.append(title, status);
        const meta = document.createElement("div");
        meta.className = "operator-details";
        for (const value of [`Base ID: ${item.base_id}`, `ESSID: ${String(item.essid_from).padStart(2, "0")}-${String(item.essid_to).padStart(2, "0")}`, `Range: ${item.range_start}-${item.range_end}`]) {
            const span = document.createElement("span");
            span.textContent = value;
            meta.append(span);
        }
        const actions = document.createElement("div");
        actions.className = "operator-actions";
        for (const [label, action] of [["Edit", "edit"], [item.active ? "Disable" : "Enable", item.active ? "disable" : "enable"], ["Delete", "delete"]]) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "secondary";
            button.textContent = label;
            button.addEventListener("click", () => perform(item, action));
            actions.append(button);
        }
        row.append(details, meta, actions);
        list.append(row);
    }
}

function updateRange() {
    const base = document.getElementById("base-id").value;
    const start = Number(document.getElementById("essid-from").value);
    const end = Number(document.getElementById("essid-to").value);
    document.getElementById("range-preview").textContent = /^[0-9]{7}$/.test(base) && start >= 0 && end <= 99 && start <= end
        ? `Range: ${base}${String(start).padStart(2, "0")}-${base}${String(end).padStart(2, "0")}` : "Range: -";
}

function openForm(item = null) {
    editing = item;
    form.reset();
    document.getElementById("form-title").textContent = item ? "Edit operator" : "Add operator";
    document.getElementById("callsign").value = item?.callsign ?? "";
    document.getElementById("base-id").value = item?.base_id ?? "";
    document.getElementById("essid-from").value = item?.essid_from ?? 0;
    document.getElementById("essid-to").value = item?.essid_to ?? 99;
    document.getElementById("active").checked = item?.active ?? true;
    updateRange();
    dialog.showModal();
}

async function request(url, method, payload) {
    showFeedback("Applying configuration...");
    const response = await fetch(url, {method, credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Configuration update failed.");
    operators = data.operators;
    render();
    showFeedback(data.message);
    try {
        const audit = await fetch("/admin/api/audit", {credentials: "same-origin"});
        if (audit.ok) {
            const events = (await audit.json()).events;
            const activity = document.getElementById("activity");
            activity.replaceChildren();
            for (const event of events) {
                const li = document.createElement("li");
                li.textContent = `${event.created_at.slice(0, 19)} ${event.action}${event.operator_callsign ? ` - ${event.operator_callsign}` : ""}`;
                activity.append(li);
            }
        }
    } catch (_) { /* The applied change remains successful. */ }
}

async function perform(item, action) {
    if (action === "edit") return openForm(item);
    if (action === "delete" && !window.confirm(`Delete ${item.callsign}? This removes DMR access and cannot be undone.`)) return;
    const suffix = action === "delete" ? "" : `/${action}`;
    try {
        await request(`/admin/api/operators/${item.id}${suffix}`, action === "delete" ? "DELETE" : "POST", action === "delete" ? {confirm_callsign: item.callsign} : {});
    } catch (error) { showFeedback(error.message, true); }
}

document.getElementById("add-operator").addEventListener("click", () => openForm());
document.getElementById("cancel").addEventListener("click", () => dialog.close());
for (const id of ["base-id", "essid-from", "essid-to"]) document.getElementById(id).addEventListener("input", updateRange);
form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
        callsign: document.getElementById("callsign").value,
        base_id: Number(document.getElementById("base-id").value),
        essid_from: Number(document.getElementById("essid-from").value),
        essid_to: Number(document.getElementById("essid-to").value),
        active: document.getElementById("active").checked
    };
    const url = editing ? `/admin/api/operators/${editing.id}` : "/admin/api/operators";
    try { await request(url, editing ? "PUT" : "POST", payload); dialog.close(); }
    catch (error) { showFeedback(error.message, true); dialog.close(); }
});

fetch("/admin/api/operators", {credentials: "same-origin"}).then((response) => response.json().then((data) => {
    if (response.ok) { operators = data.operators; render(); }
})).catch(() => showFeedback("Could not refresh operators.", true));
