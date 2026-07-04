document.querySelectorAll('.tabs').forEach(function (tabs) {
  tabs.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var target = btn.dataset.tab;
      tabs.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      tabs.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      tabs.querySelector('.tab-panel[data-tab="' + target + '"]').classList.add('active');
    });
  });
});
