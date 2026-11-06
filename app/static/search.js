(() => {
  const fold = (value) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es');

  document.querySelectorAll('[data-filter-select]').forEach((field) => {
    const select = document.querySelector(field.dataset.filterSelect);
    if (!select) return;
    const options = Array.from(select.options).slice(1);
    field.addEventListener('input', () => {
      const query = fold(field.value.trim());
      options.forEach((option) => { option.hidden = query !== '' && !fold(option.textContent).includes(query); });
      const visibleCount = options.filter((option) => !option.hidden).length;
      select.options[0].textContent = query && visibleCount === 0 ? 'No hay coincidencias' : 'Selecciona una opción';
    });
    select.addEventListener('change', () => { field.value = ''; options.forEach((option) => { option.hidden = false; }); });
  });

  const searchBox = document.querySelector('[data-global-search]');
  if (!searchBox) return;
  const input = searchBox.querySelector('input');
  const list = searchBox.querySelector('[role="listbox"]');
  let timer;
  let controller;

  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); };
  const show = (items, query) => {
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'suggestion-empty';
      empty.textContent = `No hay coincidencias para “${query}”`;
      list.append(empty);
    } else {
      items.forEach((item) => {
        const link = document.createElement('a');
        link.className = 'suggestion-item';
        link.href = item.url;
        link.setAttribute('role', 'option');
        const type = document.createElement('span');
        type.className = `suggestion-type ${item.tipo.toLowerCase()}`;
        type.textContent = item.tipo;
        const label = document.createElement('span');
        label.className = 'suggestion-label';
        label.textContent = item.texto;
        const arrow = document.createElement('span');
        arrow.className = 'suggestion-arrow';
        arrow.textContent = '↗';
        link.append(type, label, arrow);
        list.append(link);
      });
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  input.addEventListener('input', () => {
    clearTimeout(timer);
    if (controller) controller.abort();
    const query = input.value.trim();
    if (query.length < 2) { close(); return; }
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await fetch(`/buscar?q=${encodeURIComponent(query)}`, {signal: controller.signal, headers: {Accept: 'application/json'}});
        if (!response.ok) { close(); return; }
        show(await response.json(), query);
      } catch (error) {
        if (error.name !== 'AbortError') close();
      }
    }, 180);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
    if (event.key === 'Enter' && !list.hidden) {
      event.preventDefault();
      const first = list.querySelector('a');
      if (first) window.location.href = first.href;
    }
  });
  document.addEventListener('click', (event) => { if (!searchBox.contains(event.target)) close(); });
})();
