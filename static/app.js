const scoreInputs = document.querySelectorAll(".score-input");
const scoreTotal = document.querySelector("#score-total");
const scoreMeter = document.querySelector(".score-meter");
const matchForm = document.querySelector("[data-score-total]");

function refreshScoreTotal() {
  if (!scoreInputs.length || !scoreTotal || !matchForm) return;
  const target = Number(matchForm.dataset.scoreTotal);
  const total = Array.from(scoreInputs).reduce((sum, input) => sum + Number(input.value || 0), 0);
  scoreTotal.textContent = total.toLocaleString();
  scoreMeter.classList.toggle("invalid", total !== target);
}

scoreInputs.forEach((input) => input.addEventListener("input", refreshScoreTotal));
refreshScoreTotal();

document.querySelectorAll(".flash").forEach((flash) => {
  setTimeout(() => {
    flash.style.opacity = "0";
    flash.style.transform = "translateY(-6px)";
  }, 4200);
});

const menuToggle = document.querySelector(".menu-toggle");
const mobileMenu = document.querySelector(".mobile-menu");

function setMobileMenu(open) {
  if (!menuToggle || !mobileMenu) return;
  menuToggle.classList.toggle("is-open", open);
  mobileMenu.classList.toggle("is-open", open);
  menuToggle.setAttribute("aria-expanded", String(open));
}

menuToggle?.addEventListener("click", () => {
  setMobileMenu(!mobileMenu.classList.contains("is-open"));
});

mobileMenu?.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => setMobileMenu(false));
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setMobileMenu(false);
});

document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", (event) => {
    if (!window.confirm(button.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

document.querySelectorAll("select[data-filterable-select]").forEach((select) => {
  const originalOptions = Array.from(select.options).filter((option) => option.value);
  const placeholder = select.options[0]?.textContent.trim() || "";
  const searchPlaceholder = select.dataset.searchPlaceholder || placeholder;
  const emptyText = select.dataset.emptyText || "No results";
  const requiredText = select.dataset.requiredText || placeholder;
  const wasRequired = select.required;
  const listId = `${select.id}-search-list`;
  let activeIndex = -1;

  const wrapper = document.createElement("div");
  wrapper.className = "searchable-select";

  const input = document.createElement("input");
  input.type = "text";
  input.className = "searchable-select-input";
  input.placeholder = searchPlaceholder;
  input.autocomplete = "off";
  input.spellcheck = false;
  input.required = wasRequired;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", listId);

  const list = document.createElement("div");
  list.className = "searchable-select-list";
  list.id = listId;
  list.setAttribute("role", "listbox");
  list.hidden = true;

  select.parentNode.insertBefore(wrapper, select);
  wrapper.append(input, select, list);
  select.classList.add("searchable-select-native");
  select.required = false;

  const normalize = (value) => value.normalize("NFKC").toLocaleLowerCase();
  const selectedOption = () => originalOptions.find((option) => option.value === select.value);

  function closeList() {
    list.hidden = true;
    wrapper.classList.remove("is-open");
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activeIndex = -1;
  }

  function setActive(index) {
    const items = Array.from(list.querySelectorAll("[role='option']"));
    if (!items.length) return;
    activeIndex = (index + items.length) % items.length;
    items.forEach((item, itemIndex) => item.classList.toggle("is-active", itemIndex === activeIndex));
    const active = items[activeIndex];
    input.setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  }

  function choose(option) {
    select.value = option.value;
    input.value = option.textContent.trim();
    input.setCustomValidity("");
    select.dispatchEvent(new Event("change", { bubbles: true }));
    closeList();
  }

  function renderOptions(keyword = "") {
    const normalizedKeyword = normalize(keyword.trim());
    const matches = originalOptions.filter((option) => normalize(option.textContent).includes(normalizedKeyword));
    list.replaceChildren();
    activeIndex = -1;

    if (!matches.length) {
      const empty = document.createElement("div");
      empty.className = "searchable-select-empty";
      empty.textContent = emptyText;
      list.append(empty);
      return;
    }

    matches.forEach((option, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "searchable-select-option";
      item.id = `${listId}-option-${index}`;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", String(option.value === select.value));
      item.textContent = option.textContent.trim();
      item.addEventListener("mousedown", (event) => event.preventDefault());
      item.addEventListener("click", () => choose(option));
      list.append(item);
    });
  }

  function openList(showAll = false) {
    renderOptions(showAll ? "" : input.value);
    list.hidden = false;
    wrapper.classList.add("is-open");
    input.setAttribute("aria-expanded", "true");
  }

  const initialSelection = selectedOption();
  input.value = initialSelection ? initialSelection.textContent.trim() : "";
  input.setCustomValidity(wasRequired && !initialSelection ? requiredText : "");

  input.addEventListener("focus", () => openList(true));
  input.addEventListener("click", () => openList(true));
  input.addEventListener("input", () => {
    select.value = "";
    input.setCustomValidity(wasRequired ? requiredText : "");
    openList(false);
  });
  input.addEventListener("keydown", (event) => {
    const items = Array.from(list.querySelectorAll("[role='option']"));
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) openList(true);
      setActive(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Enter" && !list.hidden && activeIndex >= 0) {
      event.preventDefault();
      items[activeIndex]?.click();
    } else if (event.key === "Escape") {
      closeList();
    } else if (event.key === "Tab") {
      closeList();
    }
  });

  document.addEventListener("pointerdown", (event) => {
    if (!wrapper.contains(event.target)) closeList();
  });
});

const aRulesToggle = document.querySelector("[data-a-rules-toggle]");
const aRulesForm = aRulesToggle?.closest(".rule-form");

function refreshARulesState() {
  if (!aRulesToggle || !aRulesForm) return;
  aRulesForm.classList.toggle("is-a-rules-enabled", aRulesToggle.checked);
}

aRulesToggle?.addEventListener("change", refreshARulesState);
refreshARulesState();
