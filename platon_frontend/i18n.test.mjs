import { test } from "node:test";
import assert from "node:assert/strict";
import { startI18n, translateText } from "./i18n.js";

test("UI phrase translations round-trip between Polish and English", () => {
  const phrases = [
    "Nowa rozmowa",
    "Ustawienia agenta",
    "Filtruj dokumenty po nazwie lub kolekcji…",
    "Backend połączony",
    "Zanim Platon pójdzie dalej",
  ];
  for (const polish of phrases) {
    const english = translateText(polish, "en");
    assert.notEqual(english, polish);
    assert.equal(translateText(english, "pl"), polish);
    assert.equal(translateText(polish, "pl"), polish);
    assert.equal(translateText(english, "en"), english);
  }
});

test("dynamic UI translations preserve file, path, model, and error text", () => {
  for (const [polish, english] of [
    ['3 wybranych', '3 selected'],
    ['10 wybranych · limit osiągnięty', '10 selected · limit reached'],
    ['Dostępne modele: 30', 'Available models: 30'],
    ['Dodano dokument „notes.txt”.', 'Added document “notes.txt”.'],
    ['Wybrano źródła RAG: 2.', 'Selected RAG sources: 2.'],
  ]) {
    assert.equal(translateText(polish, 'en'), english);
    assert.equal(translateText(english, 'pl'), polish);
    assert.equal(translateText(polish, 'pl'), polish);
    assert.equal(translateText(english, 'en'), english);
  }
  assert.equal(translateText("Otwórz C:\\data\\report.pdf", "en"), "Open C:\\data\\report.pdf");
  assert.equal(translateText("Open C:\\data\\report.pdf", "en"), "Open C:\\data\\report.pdf");
  assert.equal(translateText("Otwórz C:\\data\\report.pdf", "pl"), "Otwórz C:\\data\\report.pdf");
  assert.equal(translateText("Delete document budget.xlsx", "pl"), "Usuń dokument budget.xlsx");
  assert.equal(translateText("Nie udało się otworzyć zasobu: Access denied: C:\\data", "en"), "Could not open resource: Access denied: C:\\data");
  assert.equal(translateText("my-custom-model:latest", "en"), "my-custom-model:latest");
  assert.equal(translateText("secret tool output", "en"), "secret tool output");
});

function fakeElement(tag = "div", attrs = {}) {
  const attributes = new Map(Object.entries(attrs));
  const element = {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    parentElement: null,
    childNodes: [],
    textContent: "",
    matches(selector) {
      return selector.split(", ").some((item) => item.toLowerCase() === this.tagName.toLowerCase() ||
        item.startsWith(".") && this.className.split(/\s+/).includes(item.slice(1)));
    },
    hasAttribute(name) { return attributes.has(name); },
    getAttribute(name) { return attributes.get(name); },
    setAttribute(name, value) { attributes.set(name, value); },
    append(child) { child.parentElement = this; this.childNodes.push(child); },
    get attributes() { return attributes; },
  };
  element.className = attrs.class ?? "";
  return element;
}

function fakeText(value) {
  return { nodeType: 3, nodeValue: value, parentElement: null, childNodes: [] };
}

test("DOM translation skips conversation message bodies and persists language toggles", () => {
  const body = fakeElement("body");
  const html = fakeElement("html");
  const title = fakeElement("h1");
  const titleText = fakeText("Nowa rozmowa");
  title.append(titleText);
  const input = fakeElement("input", { placeholder: "Szukaj w rozmowach…", "aria-label": "Szukaj w rozmowach" });
  const conversation = fakeElement("section");
  const userMessage = fakeElement("article", { class: "message-user" });
  const messageBody = fakeElement("div", { class: "message-body" });
  const userText = fakeText("Nowa rozmowa");
  messageBody.append(userText);
  userMessage.append(messageBody);
  conversation.append(userMessage);
  const assistant = fakeElement('article', { class: 'message-assistant' });
  const assistantBody = fakeElement('div', { class: 'message-body' });
  const prose = fakeText('Kopiuj');
  const copy = fakeElement('button', { class: 'code-copy-btn' });
  const copyText = fakeText('Kopiuj');
  copy.append(copyText);
  const figure = fakeElement('figure', { class: 'generated-image' });
  const download = fakeText('Pobierz');
  figure.append(download);
  assistantBody.append(prose);
  assistantBody.append(copy);
  assistantBody.append(figure);
  assistant.append(assistantBody);
  conversation.append(assistant);
  const select = fakeElement('select');
  select.id = 'upload-collection';
  const option = fakeElement('option');
  option.value = '__new__';
  option.textContent = 'Nowa kolekcja…';
  const optionText = fakeText('Nowa kolekcja…');
  option.append(optionText);
  select.append(option);
  body.append(select);
  const toggle = fakeElement("button");
  toggle.id = "language-toggle";
  const nodes = { "#language-toggle": toggle };
  body.append(title);
  body.append(input);
  body.append(conversation);
  body.append(toggle);
  const handlers = {};
  const document = {
    documentElement: html,
    body,
    querySelector(selector) { return nodes[selector] ?? null; },
    addEventListener(type, callback) { handlers[type] = callback; },
  };
  const data = new Map();
  const storage = { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
  const i18n = startI18n({ document, storage, preferenceApi: null });
  assert.equal(titleText.nodeValue, "Nowa rozmowa");
  assert.equal(userText.nodeValue, "Nowa rozmowa");

  handlers.click({ target: { closest: (selector) => selector === "#language-toggle" ? toggle : null } });
  assert.equal(i18n.language, "en");
  assert.equal(html.lang, "en");
  assert.equal(titleText.nodeValue, "New chat");
  assert.equal(input.getAttribute("placeholder"), "Search conversations…");
  assert.equal(input.getAttribute("aria-label"), "Search conversations");
  assert.equal(userText.nodeValue, "Nowa rozmowa");
  assert.equal(toggle.textContent, "PL");
  assert.equal(prose.nodeValue, 'Kopiuj');
  assert.equal(copyText.nodeValue, 'Copy');
  assert.equal(download.nodeValue, 'Download');
  assert.equal(optionText.nodeValue, 'New collection…');
  assert.equal(data.get("platon.language"), "en");

  i18n.setLanguage("pl");
  assert.equal(titleText.nodeValue, "Nowa rozmowa");
  assert.equal(input.getAttribute("placeholder"), "Szukaj w rozmowach…");
  assert.equal(copyText.nodeValue, 'Kopiuj');
  assert.equal(download.nodeValue, 'Pobierz');
  assert.equal(optionText.nodeValue, 'Nowa kolekcja…');
});
