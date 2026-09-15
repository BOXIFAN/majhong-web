// 比赛录入：这里只做即时反馈，最终点数校验仍由后端负责。
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

// 提示消息淡出后仍保留在 DOM 中，避免读屏软件在读取过程中节点突然消失。
document.querySelectorAll(".flash").forEach((flash) => {
  setTimeout(() => {
    flash.style.opacity = "0";
    flash.style.transform = "translateY(-6px)";
  }, 4200);
});

// 移动端导航的视觉状态与 aria-expanded 必须同步更新。
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

// 所有破坏性表单通过 data-confirm 复用同一套二次确认逻辑。
document.querySelectorAll("[data-confirm]").forEach((button) => {
  button.addEventListener("click", (event) => {
    if (!window.confirm(button.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

/*
 * 可搜索下拉框保留原生 select 作为提交数据的唯一来源，自定义输入框只代理交互。
 * 因此 choose/input 两条路径都必须同步 select.value；required 校验则转移到可见输入框，
 * 否则浏览器会尝试聚焦已隐藏的原生控件。
 */
document.querySelectorAll("select[data-filterable-select]").forEach((select) => {
  const originalOptions = Array.from(select.options).filter((option) => option.value);
  const placeholder = select.options[0]?.textContent.trim() || "";
  const searchPlaceholder = select.dataset.searchPlaceholder || placeholder;
  const listLabel = select.dataset.listLabel || "List";
  const emptyText = select.dataset.emptyText || "No results";
  const requiredText = select.dataset.requiredText || placeholder;
  const wasRequired = select.required;
  const listId = `${select.id}-search-list`;
  let activeIndex = -1;

  const wrapper = document.createElement("div");
  wrapper.className = "searchable-select";

  const controls = document.createElement("div");
  controls.className = "searchable-select-controls";

  const input = document.createElement("input");
  input.type = "search";
  input.className = "searchable-select-input";
  input.placeholder = searchPlaceholder;
  input.autocomplete = "off";
  input.spellcheck = false;
  input.enterKeyHint = "search";
  input.required = wasRequired;
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", listId);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "searchable-select-toggle";
  toggle.setAttribute("aria-controls", listId);
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-label", listLabel);

  const toggleLabel = document.createElement("span");
  toggleLabel.className = "searchable-select-toggle-label";
  toggleLabel.textContent = listLabel;

  const toggleIcon = document.createElement("span");
  toggleIcon.className = "searchable-select-toggle-icon";
  toggleIcon.setAttribute("aria-hidden", "true");
  toggle.append(toggleLabel, toggleIcon);

  const list = document.createElement("div");
  list.className = "searchable-select-list";
  list.id = listId;
  list.setAttribute("role", "listbox");
  list.hidden = true;

  select.parentNode.insertBefore(wrapper, select);
  controls.append(input, toggle);
  wrapper.append(controls, select, list);
  select.classList.add("searchable-select-native");
  select.required = false;

  // NFKC 让全角/半角字符以相同形式参与筛选，方便中英文混合的玩家名称。
  const normalize = (value) => value.normalize("NFKC").toLocaleLowerCase();
  const selectedOption = () => originalOptions.find((option) => option.value === select.value);

  function closeList() {
    list.hidden = true;
    wrapper.classList.remove("is-open");
    input.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-expanded", "false");
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
    toggle.setAttribute("aria-expanded", "true");
  }

  const initialSelection = selectedOption();
  input.value = initialSelection ? initialSelection.textContent.trim() : "";
  input.setCustomValidity(wasRequired && !initialSelection ? requiredText : "");

  input.addEventListener("input", () => {
    select.value = "";
    input.setCustomValidity(wasRequired ? requiredText : "");
    openList(false);
  });
  toggle.addEventListener("click", () => {
    if (list.hidden) {
      openList(true);
    } else {
      closeList();
    }
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

  // 每个控件监听一次全局点击；页面上的控件数量较少，保持实现简单且相互独立。
  document.addEventListener("pointerdown", (event) => {
    if (!wrapper.contains(event.target)) closeList();
  });
});

// A 规则只控制相关字段的可见状态，字段值始终随表单提交并由后端解析。
const aRulesToggle = document.querySelector("[data-a-rules-toggle]");
const aRulesForm = aRulesToggle?.closest(".rule-form");

function refreshARulesState() {
  if (!aRulesToggle || !aRulesForm) return;
  aRulesForm.classList.toggle("is-a-rules-enabled", aRulesToggle.checked);
}

aRulesToggle?.addEventListener("change", refreshARulesState);
refreshARulesState();

// 记账表单：根据收入/支出切换可用分类，支出时禁用会员关联。
document.querySelectorAll("[data-finance-kind]").forEach((kindSelect) => {
  const form = kindSelect.closest("form");
  const categorySelect = form?.querySelector("[data-finance-category]");
  const memberSelect = form?.querySelector("[data-finance-member]");

  function refreshFinanceFields() {
    const isIncome = kindSelect.value === "income";
    if (categorySelect) {
      let firstVisible = "";
      Array.from(categorySelect.options).forEach((option) => {
        const set = option.dataset.catset;
        const visible = set === "both" || set === kindSelect.value;
        option.hidden = !visible;
        if (visible && !firstVisible) firstVisible = option.value;
      });
      if (!Array.from(categorySelect.options).some((option) => !option.hidden && option.selected)) {
        categorySelect.value = firstVisible;
      }
    }
    if (memberSelect) memberSelect.disabled = !isIncome;
  }

  kindSelect.addEventListener("change", refreshFinanceFields);
  refreshFinanceFields();
});

// 公告展开/收起：切换 line-clamp 并更新按钮文案。
document.querySelectorAll("[data-expand-target]").forEach((button) => {
  const target = document.getElementById(button.dataset.expandTarget);
  if (!target) return;
  const expandLabel = button.dataset.labelExpand;
  const collapseLabel = button.dataset.labelCollapse;
  button.addEventListener("click", () => {
    const expanded = target.classList.toggle("is-expanded");
    button.textContent = expanded ? collapseLabel : expandLabel;
  });
});

/*
 * Plan B：数据叙事动效。
 * 两件事：把模板里的 data-vt 转成跨页面共享元素名；把标记过的数字滚到目标值。
 * 服务端渲染的文本始终是最终值，脚本未执行或被降级时页面照常显示。
 */
(() => {
  // 共享元素命名集中在脚本里控制，模板只声明“哪个节点参与转场”。
  document.querySelectorAll("[data-vt]").forEach((el) => {
    el.style.viewTransitionName = el.dataset.vt;
  });

  const countUpTargets = Array.from(document.querySelectorAll("[data-countup]"));
  if (!countUpTargets.length) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  // 前缀/数值/后缀三段式：A$1,234.56、12.3%、-320 都能就地还原。
  const numberPattern = /^(\D*?)(-?[\d,]+(?:\.\d+)?)(\D*)$/;

  function formatNumber(value, decimals, grouped) {
    let text = value.toFixed(decimals);
    if (grouped) {
      const [whole, fraction] = text.split(".");
      text = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (fraction ? `.${fraction}` : "");
    }
    return text;
  }

  function roll(el) {
    const original = el.textContent.trim();
    const parts = original.match(numberPattern);
    if (!parts) return;

    const [, prefix, raw, suffix] = parts;
    const target = Number(raw.replace(/,/g, ""));
    if (!Number.isFinite(target) || target === 0) return;

    const decimals = (raw.split(".")[1] || "").length;
    const grouped = raw.includes(",");
    const negative = target < 0;
    const magnitude = Math.abs(target);
    const duration = 700;

    // 延后一点再起步，让整页转场的首帧截到的是服务端的最终值而不是中途数字。
    window.setTimeout(() => {
      const start = performance.now();

      function frame(now) {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        const shown = formatNumber(magnitude * eased, decimals, grouped);
        el.textContent = `${prefix}${negative ? "-" : ""}${shown}${suffix}`;
        if (progress < 1) {
          requestAnimationFrame(frame);
        } else {
          el.textContent = original; // 收尾回到服务端原文，避免任何格式误差
        }
      }

      requestAnimationFrame(frame);
    }, 120);
  }

  if (!("IntersectionObserver" in window)) {
    countUpTargets.forEach(roll);
    return;
  }

  // 只在数字进入视口时滚动一次，长页面下半部分不会在加载时就白白播完。
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        observer.unobserve(entry.target);
        roll(entry.target);
      });
    },
    { rootMargin: "0px 0px -12% 0px" }
  );

  countUpTargets.forEach((el) => observer.observe(el));
})();
