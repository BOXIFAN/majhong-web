/* 移动端 App（PWA）：页面路由、主题切换、Dock 与录入比赛实时算分。 */

(function () {
  "use strict";

  var root = document.documentElement;
  var body = document.body;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var themeMeta = document.querySelector('meta[name="theme-color"]');

  var i18n = {};
  var i18nEl = document.getElementById("appI18n");
  if (i18nEl) {
    try {
      i18n = JSON.parse(i18nEl.textContent || "{}");
    } catch (error) {
      i18n = {};
    }
  }

  /* ---------------- 主题 ---------------- */
  var THEME_KEY = "brml-theme";

  function applyTheme(theme) {
    root.dataset.theme = theme;
    if (themeMeta) {
      themeMeta.setAttribute("content", theme === "dark" ? "#080c11" : "#eef1f7");
    }
  }

  applyTheme(root.dataset.theme === "dark" ? "dark" : "light");

  var themeButton = document.getElementById("themeToggle");

  function toggleTheme(originX, originY) {
    var next = root.dataset.theme === "dark" ? "light" : "dark";
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch (error) {
      /* 隐私模式下忽略 */
    }
    if (!document.startViewTransition || reduceMotion) {
      applyTheme(next);
      return;
    }
    var x = typeof originX === "number" ? originX : window.innerWidth - 32;
    var y = typeof originY === "number" ? originY : 32;
    var radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y));
    var transition = document.startViewTransition(function () {
      applyTheme(next);
    });
    transition.ready.then(function () {
      // 只做圆形裁切：布局与字号完全不动
      root.animate(
        {
          clipPath: [
            "circle(0px at " + x + "px " + y + "px)",
            "circle(" + radius + "px at " + x + "px " + y + "px)"
          ]
        },
        {
          duration: 620,
          easing: "cubic-bezier(.22,.61,.36,1)",
          pseudoElement: "::view-transition-new(root)"
        }
      );
    });
  }

  if (themeButton) {
    themeButton.addEventListener("click", function (event) {
      var rect = themeButton.getBoundingClientRect();
      toggleTheme(
        event.clientX || rect.left + rect.width / 2,
        event.clientY || rect.top + rect.height / 2
      );
    });
  }

  /* ---------------- Dock 玻璃高光 ---------------- */
  Array.prototype.forEach.call(document.querySelectorAll(".glass"), function (el) {
    el.addEventListener("pointermove", function (event) {
      var rect = el.getBoundingClientRect();
      el.style.setProperty("--sheen-x", ((event.clientX - rect.left) / rect.width) * 100 + "%");
      el.style.setProperty("--sheen-y", ((event.clientY - rect.top) / rect.height) * 100 + "%");
    });
    el.addEventListener("pointerleave", function () {
      el.style.setProperty("--sheen-x", "50%");
      el.style.setProperty("--sheen-y", "0%");
    });
  });

  /* ---------------- 提示条 ---------------- */
  var toast = document.getElementById("appToast");
  var toastTimer = null;

  function showToast(message, kind) {
    if (!toast) {
      return;
    }
    toast.textContent = message;
    toast.className = "toast show" + (kind ? " " + kind : "");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toast.className = "toast" + (kind ? " " + kind : "");
    }, 2600);
  }

  var flashData = document.getElementById("flashData");
  if (flashData) {
    try {
      var messages = JSON.parse(flashData.textContent || "[]");
      if (messages.length) {
        var first = messages[0];
        var kind = first[0] === "error" ? "error" : (first[0] === "success" ? "success" : "");
        var joined = messages.map(function (item) { return item[1]; }).join(" · ");
        window.setTimeout(function () { showToast(joined, kind || "error"); }, 120);
      }
    } catch (error) {
      /* 忽略解析失败 */
    }
  }

  /* ---------------- 页面路由 ---------------- */
  var viewEls = {};
  Array.prototype.forEach.call(document.querySelectorAll(".view"), function (view) {
    viewEls[view.dataset.view] = view;
  });

  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab[data-route]"));
  var addMatch = document.getElementById("addMatch");
  var canEnterMatch = !!(addMatch && !addMatch.classList.contains("is-locked"));
  // 子页面（个人页/规则/活动/头像）归属「我的」这个 Tab
  var PARENT_TAB = { profile: "me", rules: "me", meetups: "me", avatar: "me", match: "matches" };
  var currentView = null;
  var currentMatchId = null;
  var scrollMemory = {};

  function routeFromHash() {
    var raw = window.location.hash.replace(/^#\/?/, "").trim();
    var detail = raw.match(/^match\/(\d+)$/);
    if (detail && viewEls.match) {
      currentMatchId = Number(detail[1]);
      return "match";
    }
    if (viewEls[raw]) {
      return raw;
    }
    var fallback = body.dataset.defaultView || "leaderboard";
    return viewEls[fallback] ? fallback : "leaderboard";
  }

  function render(route) {
    var target = viewEls[route] ? route : "leaderboard";
    var changed = currentView !== target;

    // 一次性收敛所有页面，避免直接带 hash 打开时出现两个视图同时可见。
    Object.keys(viewEls).forEach(function (key) {
      if (key === target) {
        return;
      }
      viewEls[key].hidden = true;
      viewEls[key].classList.remove("is-active");
    });

    if (changed && currentView && viewEls[currentView]) {
      scrollMemory[currentView] = window.scrollY;
    }

    var view = viewEls[target];
    if (target === "match") {
      renderMatchDetail(currentMatchId);
    }
    view.hidden = false;
    if (changed) {
      view.classList.remove("is-active");
      if (!reduceMotion) {
        void view.offsetWidth; // 重新触发进场动画
      }
      view.classList.add("is-active");
    }

    var activeTab = PARENT_TAB[target] || target;
    tabs.forEach(function (tab) {
      tab.setAttribute("aria-current", tab.dataset.route === activeTab ? "true" : "false");
    });
    if (addMatch) {
      addMatch.setAttribute("aria-current", target === "entry" ? "true" : "false");
    }

    currentView = target;
    if (changed) {
      window.scrollTo(0, scrollMemory[target] || 0);
    }
  }

  function navigate(route, param) {
    if (route === "entry" && !canEnterMatch) {
      if (addMatch) {
        addMatch.classList.remove("shake");
        void addMatch.offsetWidth;
        addMatch.classList.add("shake");
      }
      showToast(i18n.entryLocked || "", "error");
      return;
    }
    if (!viewEls[route]) {
      return;
    }
    if (route === "match" && param) {
      currentMatchId = Number(param);
    }
    var target = route === "match" && currentMatchId ? "#/match/" + currentMatchId : "#/" + route;
    if (window.location.hash === target) {
      render(route);
      return;
    }
    window.location.hash = target;
  }

  window.addEventListener("hashchange", function () {
    render(routeFromHash());
  });

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      navigate(tab.dataset.route);
    });
  });

  if (addMatch) {
    addMatch.addEventListener("click", function () {
      navigate("entry");
    });
  }

  // 页面内的入口（列表按钮、返回按钮）同样走 App 内路由，不跳转整站页面
  document.addEventListener("click", function (event) {
    var matchRow = event.target.closest ? event.target.closest("[data-match-id]") : null;
    if (matchRow) {
      event.preventDefault();
      navigate("match", matchRow.dataset.matchId);
      return;
    }
    var trigger = event.target.closest ? event.target.closest("[data-route]") : null;
    if (!trigger || trigger.classList.contains("tab") || trigger === addMatch) {
      return;
    }
    event.preventDefault();
    navigate(trigger.dataset.route);
  });

  /* ---------------- 比赛详情 ---------------- */
  var matchData = {};
  var matchDataEl = document.getElementById("matchData");
  if (matchDataEl) {
    try {
      matchData = JSON.parse(matchDataEl.textContent || "{}");
    } catch (error) {
      matchData = {};
    }
  }

  function signed(value) {
    var numeric = Number(value) || 0;
    if (!numeric) {
      return "±0.0";
    }
    return (numeric > 0 ? "+" : "−") + Math.abs(numeric).toFixed(1);
  }

  function placeText(placement) {
    var value = Number(placement);
    return Number.isInteger(value)
      ? (i18n.place || "{place}").replace("{place}", value)
      : (i18n.placeTied || "{place}").replace("{place}", value);
  }

  function renderMatchDetail(id) {
    if (!id) {
      return;
    }
    var match = matchData[String(id)];
    var title = document.getElementById("matchTitle");
    var subtitle = document.getElementById("matchSubtitle");
    var total = document.getElementById("matchTotal");
    var meta = document.getElementById("matchMeta");
    var list = document.getElementById("matchEntries");
    var note = document.getElementById("matchNote");
    if (!list) {
      return;
    }
    if (!match) {
      showToast(i18n.matchNotFound || "", "error");
      return;
    }
    if (title) {
      title.textContent = match.date_label + " " + match.weekday + " " + match.time_label;
    }
    if (subtitle) {
      subtitle.textContent = [match.type, match.referee || ""].filter(Boolean).join(" · ");
    }
    if (total) {
      total.textContent = i18n.matchBreakdown || "";
    }
    if (meta) {
      meta.textContent =
        (i18n.totalLabel || "") + " " + match.total.toLocaleString("en-US") +
        (match.memo ? " · " + match.memo : "");
    }

    list.textContent = "";
    match.entries.forEach(function (entry) {
      var row = document.createElement("div");
      row.className = "rules-row detail-row";

      var label = document.createElement("span");
      label.className = "rules-label";
      var name = document.createElement("strong");
      name.textContent = entry.name;
      var detail = document.createElement("small");
      detail.textContent =
        entry.score.toLocaleString("en-US") + " · " + placeText(entry.placement) +
        " · " + (i18n.scoreLabel || "点数") + " " + signed(entry.base) +
        " · UMA " + signed(entry.uma) +
        (entry.penalty ? " · " + (i18n.penaltyLabel || "罚分") + " −" + entry.penalty : "") +
        (entry.penalty_reason ? "（" + entry.penalty_reason + "）" : "");
      label.appendChild(name);
      label.appendChild(detail);

      var value = document.createElement("span");
      value.className = "rules-value " + (entry.points > 0 ? "pos-text" : (entry.points < 0 ? "neg-text" : ""));
      value.textContent = signed(entry.points);

      row.appendChild(label);
      row.appendChild(value);
      list.appendChild(row);
    });

    if (note) {
      note.textContent = (i18n.matchScoringNote || "").replace(
        "{return_points}",
        (match.return_points || 0).toLocaleString("en-US")
      );
    }
  }

  render(routeFromHash());

  /* ---------------- 录入比赛：实时预览算分 ---------------- */
  var form = document.getElementById("entryForm");

  if (form) {
    var rules = {};
    var rulesEl = document.getElementById("entryRules");
    if (rulesEl) {
      try {
        rules = JSON.parse(rulesEl.textContent || "{}");
      } catch (error) {
        rules = {};
      }
    }

    var returnPoints = Number(rules.return_points || rules.default_starting_points || 30000);
    var startTotal = Number(form.dataset.startTotal || 100000);
    var seatEls = Array.prototype.slice.call(form.querySelectorAll(".seat[data-seat]"));
    var totalChip = document.getElementById("totalChip");
    var totalTexts = {
      ok: form.dataset.totalOk || "",
      bad: form.dataset.totalBad || ""
    };

    function umaPoints(scores) {
      if (rules.use_a_rules) {
        var positive = scores.filter(function (score) { return score >= returnPoints; }).length;
        positive = Math.max(1, Math.min(3, positive));
        return [
          Number(rules["a_uma_" + positive + "_positive_1st"] || 0),
          Number(rules["a_uma_" + positive + "_positive_2nd"] || 0),
          Number(rules["a_uma_" + positive + "_positive_3rd"] || 0),
          Number(rules["a_uma_" + positive + "_positive_4th"] || 0)
        ];
      }
      return [
        Number(rules.uma_1st || 0),
        Number(rules.uma_2nd || 0),
        Number(rules.uma_3rd || 0),
        Number(rules.uma_4th || 0)
      ];
    }

    function placementsFor(scores) {
      var sorted = scores.slice().sort(function (a, b) { return b - a; });
      return scores.map(function (score) {
        var hits = [];
        sorted.forEach(function (value, index) {
          if (value === score) {
            hits.push(index + 1);
          }
        });
        return hits.length ? hits.reduce(function (a, b) { return a + b; }, 0) / hits.length : 4;
      });
    }

    function ranksFor(scores, index) {
      var sorted = scores.slice().sort(function (a, b) { return b - a; });
      var ranks = [];
      sorted.forEach(function (value, position) {
        if (value === scores[index]) {
          ranks.push(position + 1);
        }
      });
      return ranks.length ? ranks : [4];
    }

    function formatPoints(value) {
      if (!value) {
        return "±0.0";
      }
      return (value > 0 ? "+" : "−") + Math.abs(value).toFixed(1);
    }

    function renderEntry() {
      var seats = seatEls.map(function (el) {
        var scoreInput = el.querySelector('[data-in="score"]');
        var penaltyInput = el.querySelector('[data-in="penalty"]');
        var reasonField = el.querySelector("[data-reason-for]");
        var penalty = Number(penaltyInput && penaltyInput.value) || 0;
        if (reasonField) {
          reasonField.hidden = penalty <= 0;
        }
        return {
          el: el,
          score: Number(scoreInput && scoreInput.value) || 0,
          penalty: penalty
        };
      });

      var scores = seats.map(function (seat) { return seat.score; });
      var places = placementsFor(scores);
      var uma = umaPoints(scores);
      var total = scores.reduce(function (sum, value) { return sum + value; }, 0);

      seats.forEach(function (seat, index) {
        var ranks = ranksFor(scores, index);
        var average = ranks.reduce(function (sum, rank) { return sum + uma[rank - 1]; }, 0) / ranks.length;
        var points = Math.round(((seat.score - returnPoints) / 1000 + average - seat.penalty) * 10) / 10;
        var place = places[index];

        var placeEl = seat.el.querySelector('[data-out="place"]');
        var ptsEl = seat.el.querySelector('[data-out="points"]');
        if (placeEl) {
          placeEl.textContent = Number.isInteger(place)
            ? (i18n.place || "{place}").replace("{place}", place)
            : (i18n.placeTied || "{place}").replace("{place}", place);
          placeEl.classList.toggle("is-first", place === 1);
        }
        if (ptsEl) {
          ptsEl.textContent = formatPoints(points);
          ptsEl.classList.toggle("pos", points > 0);
          ptsEl.classList.toggle("neg", points < 0);
        }
      });

      if (totalChip) {
        var ok = total === startTotal;
        var formatted = total.toLocaleString("en-US");
        totalChip.textContent = (ok ? totalTexts.ok : totalTexts.bad).replace("{total}", formatted);
        totalChip.classList.toggle("good", ok);
        totalChip.classList.toggle("bad", !ok);
      }
      return total === startTotal;
    }

    form.addEventListener("input", function (event) {
      var target = event.target;
      if (target && (target.matches('[data-in="score"]') || target.matches('[data-in="penalty"]') || target.matches('[data-in="player"]'))) {
        renderEntry();
      }
    });

    form.addEventListener("submit", function (event) {
      // 只拦下客户端就能确定的一点：持点合计。其余校验仍交给服务端。
      if (!renderEntry()) {
        event.preventDefault();
        showToast(
          (i18n.totalMismatch || "{total}").replace("{total}", startTotal.toLocaleString("en-US")),
          "error"
        );
      }
    });

    renderEntry();
  }

  /* ---------------- Service Worker ---------------- */
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).catch(function () {
        /* 本地 http 或隐私模式下注册失败不影响使用 */
      });
    });
  }
})();
