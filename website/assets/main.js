// 灵燕智能官网 — 导航与进场动画（无依赖）
(function () {
  var nav = document.querySelector(".nav");
  var burger = document.getElementById("navBurger");
  var links = document.getElementById("navLinks");

  // 吸顶后加细边与浅影
  var onScroll = function () {
    nav.classList.toggle("is-scrolled", window.scrollY > 8);
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // 移动端菜单
  burger.addEventListener("click", function () {
    var open = links.classList.toggle("is-open");
    burger.classList.toggle("is-open", open);
    burger.setAttribute("aria-expanded", String(open));
    burger.setAttribute("aria-label", open ? "关闭菜单" : "打开菜单");
  });
  // 点了站内链接后收起
  links.addEventListener("click", function (e) {
    if (e.target.closest("a")) {
      links.classList.remove("is-open");
      burger.classList.remove("is-open");
      burger.setAttribute("aria-expanded", "false");
    }
  });

  // 进场动画（仅在支持 IO 时启用隐藏态，避免全页截图/无 JS 环境白屏）
  document.documentElement.classList.add("js");
  var revealed = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
    );
    revealed.forEach(function (el) { io.observe(el); });
  } else {
    revealed.forEach(function (el) { el.classList.add("is-in"); });
  }
})();
