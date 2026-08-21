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
