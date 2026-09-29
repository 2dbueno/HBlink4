"use strict";

const list = document.getElementById("operators");
const dialog = document.getElementById("operator-dialog");
const form = document.getElementById("operator-form");
const feedback = document.getElementById("feedback");
const csrf = document.getElementById("admin-data").dataset.csrf;
let operators = [];
let editing = null;

async function apiRequest(url, method = "GET", payload = null) {
    const options = {method, credentials: "same-origin"};
    if (payload !== null) {
        options.headers = {"Content-Type": "application/json", "X-CSRF-Token": csrf};
        options.body = JSON.stringify(payload);
    }
    let response;
    try {
        response = await fetch(url, options);
    } catch (_) {
        throw new Error("Falha de conexão. Verifique o painel e tente novamente.");
    }
    let data;
    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }
    if (!response.ok) {
        const fallback = {
            401: "Sessão expirada. Entre novamente.",
            403: "Acesso negado ou token CSRF inválido. Atualize a página e tente novamente.",
            404: "Endpoint da API administrativa não encontrado.",
            409: "Conflito de configuração. Atualize a página e tente novamente.",
            422: "Dados do operador inválidos.",
            500: "Erro interno do painel. Nenhuma alteração foi confirmada.",
            503: "Atualização da configuração indisponível."
        };
        const serverMessage = data && typeof data.error === "string" ? data.error.slice(0, 300) : "";
        throw new Error(response.status >= 500 && response.status !== 503
            ? fallback[500] : serverMessage || fallback[response.status] || `Falha na solicitação (HTTP ${response.status}).`);
    }
    if (!data || typeof data !== "object") throw new Error("Resposta inválida da API do painel.");
    return data;
}

function showFeedback(message, error = false) {
    feedback.textContent = message;
    feedback.className = error ? "error" : "success";
}

function render() {
    list.replaceChildren();
    if (!operators.length) {
        const empty = document.createElement("p");
        empty.textContent = "Nenhum operador configurado.";
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
        status.textContent = item.active ? "Ativo" : "Desativado";
        details.append(title, status);
        const meta = document.createElement("div");
        meta.className = "operator-details";
        for (const value of [`ID base: ${item.base_id}`, `ESSID: ${String(item.essid_from).padStart(2, "0")}-${String(item.essid_to).padStart(2, "0")}`, `Faixa: ${item.range_start}-${item.range_end}`]) {
            const span = document.createElement("span");
            span.textContent = value;
            meta.append(span);
        }
        const actions = document.createElement("div");
        actions.className = "operator-actions";
        for (const [label, action] of [["Editar", "edit"], [item.active ? "Desativar" : "Ativar", item.active ? "disable" : "enable"], ["Excluir", "delete"]]) {
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
        ? `Faixa: ${base}${String(start).padStart(2, "0")}-${base}${String(end).padStart(2, "0")}` : "Faixa: -";
}

function openForm(item = null) {
    editing = item;
    form.reset();
    document.getElementById("form-title").textContent = item ? "Editar operador" : "Adicionar operador";
    document.getElementById("callsign").value = item?.callsign ?? "";
    document.getElementById("base-id").value = item?.base_id ?? "";
    document.getElementById("essid-from").value = item?.essid_from ?? 0;
    document.getElementById("essid-to").value = item?.essid_to ?? 99;
    document.getElementById("active").checked = item?.active ?? true;
    updateRange();
    dialog.showModal();
}

async function request(url, method, payload) {
    showFeedback("Aplicando configuração...");
    const data = await apiRequest(url, method, payload);
    operators = data.operators;
    render();
    showFeedback("Alterações aplicadas com sucesso.");
    try {
        const audit = await apiRequest("/admin/api/audit");
        if (Array.isArray(audit.events)) {
            const events = audit.events;
            const activity = document.getElementById("activity");
            activity.replaceChildren();
            for (const event of events) {
                const li = document.createElement("li");
                li.textContent = `${event.created_at.slice(0, 19)} ${formatAuditAction(event.action)}${event.operator_callsign ? ` - ${event.operator_callsign}` : ""}`;
                activity.append(li);
            }
        }
    } catch (_) { /* The applied change remains successful. */ }
}

function formatAuditAction(action) {
    const labels = {
        admin_bootstrap: "administração inicial",
        admin_login_failure: "falha de entrada",
        admin_login_success: "entrada realizada",
        admin_logout: "saída realizada",
        operator_created: "operador adicionado",
        operator_updated: "operador atualizado",
        operator_enabled: "operador ativado",
        operator_disabled: "operador desativado",
        operator_deleted: "operador excluído",
        config_apply_success: "configuração aplicada",
        config_apply_failure: "falha ao aplicar configuração",
        config_rollback: "configuração revertida"
    };
    return labels[action] || action;
}

async function perform(item, action) {
    if (action === "edit") return openForm(item);
    if (action === "delete" && !window.confirm(`Excluir ${item.callsign}? Isso remove o acesso DMR e não pode ser desfeito.`)) return;
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

apiRequest("/admin/api/operators").then((data) => {
    if (!Array.isArray(data.operators)) throw new Error("Lista de operadores inválida na API do painel.");
    operators = data.operators;
    render();
}).catch((error) => showFeedback(error.message, true));
