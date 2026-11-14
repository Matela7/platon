'use strict';
async function refresh() {
  try {
    const status = await window.platonWindow.setupStatus();
    document.getElementById('status').textContent = status?.message || 'Preparing...';
    document.getElementById('model').textContent = status?.model || '';
    const progress = document.getElementById('progress');
    if (status?.total > 0) { progress.max = status.total; progress.value = status.completed || 0; }
    else progress.removeAttribute('value');
  } catch { document.getElementById('status').textContent = 'Waiting for backend...'; }
}
void refresh();
setInterval(refresh, 500);
