(() => {
  const items = Array.from(document.querySelectorAll("[data-review-item]"));
  let current = Math.max(0, items.findIndex((item) => !item.hidden));

  function show(index) {
    if (!items.length) return;
    current = (index + items.length) % items.length;
    items.forEach((item, position) => {
      item.hidden = position !== current;
    });
    items[current].querySelector("mark")?.scrollIntoView({ block: "center" });
    items[current].querySelector("textarea, select, button")?.focus();
  }

  function click(action) {
    items[current]?.querySelector(`[data-action="${action}"]`)?.click();
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest('[data-action="next"]')) {
      show(current + 1);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea, select")) return;
    const action = { a: "approve", r: "reject", c: "correct", n: "next" }[
      event.key.toLowerCase()
    ];
    if (action) {
      event.preventDefault();
      click(action);
    }
  });

  show(current);
})();
