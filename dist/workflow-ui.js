// Shared display copy for the fixed demo artifacts shown after the concept stage.
window.makoraDemo = {
  notice: 'Демонстрационный пример «Тихий кампус». План и мок-данные не обновляются автоматически после изменения идеи.',
  markup() { return `<div class="demo-context-note" role="note">${this.notice}</div>`; }
};
