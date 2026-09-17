/* Presentation only: reserve room for multiline feedback above the action dock. */
(() => {
  const dock = document.querySelector('.action-dock');
  const header = document.querySelector('.app-chrome');
  if (typeof ResizeObserver !== 'function') return;
  const observer = new ResizeObserver(() => {
    document.documentElement.style.setProperty('--action-dock-height', `${Math.ceil(dock?.getBoundingClientRect().height || 0)}px`);
    document.documentElement.style.scrollPaddingTop = `${Math.ceil(header?.getBoundingClientRect().height || 0) + 12}px`;
  });
  if (dock) observer.observe(dock);
  if (header) observer.observe(header);
})();
