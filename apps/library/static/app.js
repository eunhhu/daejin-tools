import {filterRooms, cellState, timeAxis, kstNow} from './model.js';
import {createBookingUI} from './booking-ui.js';

export async function boot(doc = document, fetcher = globalThis.fetch, now = kstNow,
  navigate = url => doc.defaultView?.location.assign(url)) {
  const $ = selector => doc.querySelector(selector);
  let snapshot = null, group = 'all', controller = null, serial = 0, configuration = {}, reauthenticating = false;
  const reauthenticate = () => {
    if (!reauthenticating) {reauthenticating=true;navigate('/login');}
  };
  const booking = createBookingUI(doc, fetcher, () => configuration, () => {
    snapshot = null;$('#schedule thead').replaceChildren();$('#schedule tbody').replaceChildren();
    $('#table-wrap').hidden=true;$('#summary').textContent='예약 후 시간표 갱신 필요';
    $('#status').textContent='최신 시간 확인에는 새로고침이 필요합니다.';
  }, reauthenticate);
  const element = (tag, text, className) => {
    const node = doc.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const setMessage = text => {
    $('#message').textContent = text;
    $('#message').hidden = !text;
  };
  const responseError = async (response, fallback) => {
    try {
      const data = await response.json();
      return typeof data.detail === 'string' ? data.detail : fallback;
    } catch {
      return fallback;
    }
  };
  const validDate = () => {
    const input = $('#date');
    return /^\d{4}-\d{2}-\d{2}$/.test(input.value) && Boolean(input.min) &&
      input.value >= input.min && input.value <= input.max;
  };
  const dateButtons = () => {
    const value = $('#date').value;
    $('#prev').disabled = !validDate() || value <= $('#date').min;
    $('#next').disabled = !validDate() || value >= $('#date').max;
    $('#day-label').textContent = value ? new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', weekday: 'short',
    }).format(new Date(`${value}T12:00:00+09:00`)) : '날짜';
  };
  function openSlot(room, time) {
    booking.open(room, snapshot.date, time);
  }
  function render() {
    const head = $('#schedule thead'), body = $('#schedule tbody');
    head.replaceChildren(); body.replaceChildren();
    if (!snapshot || snapshot.date !== $('#date').value) return;
    const people = Math.min(99, Math.max(1, Number($('#capacity').value) || 1));
    const rooms = filterRooms(snapshot.rooms, group, people);
    const current = now();
    $('#empty').hidden = rooms.length !== 0;
    $('#table-wrap').hidden = rooms.length === 0;
    const available = rooms.filter(room => room.starts.some(t =>
      cellState(room, t, snapshot.date, current) === 'available')).length;
    $('#summary').textContent = `${rooms.length}개 호실 · 예약 시작 가능 ${available}곳`;
    const header = element('tr');
    header.append(element('th', '시작 시간'));
    for (const room of rooms) {
      const th = element('th', room.name);
      th.scope = 'col';
      th.append(element('small', `${room.minimum}–${room.capacity}인`));
      header.append(th);
    }
    head.append(header);
    $('#schedule').style.minWidth = `${64 + rooms.length * 98}px`;
    for (const time of timeAxis(rooms)) {
      const tr = element('tr'), rowHeader = element('th', time);
      rowHeader.scope = 'row';tr.append(rowHeader);
      for (const room of rooms) {
        const state = cellState(room, time, snapshot.date, current);
        const label = {available: '가능', unavailable: '—', unknown: '?', elapsed: '·'}[state];
        const labelLong = {available: '시작 가능', unavailable: '선택 불가', unknown: '확인 불가', elapsed: '지난 시간'}[state];
        const cell = element(state === 'available' ? 'button' : 'span', label, `cell ${state}`);
        cell.setAttribute('aria-label', `${room.name} ${time} ${labelLong}`);
        cell.title = `${room.name} · ${time} · ${labelLong}`;
        if (state === 'available') {cell.type='button';cell.addEventListener('click', () => openSlot(room, time));}
        const td = element('td');td.append(cell);tr.append(td);
      }
      body.append(tr);
    }
  }
  async function load() {
    controller?.abort(); controller = new AbortController();
    const ticket = ++serial, day = $('#date').value;
    dateButtons(); $('#refresh').disabled = true;
    snapshot = null;
    $('#schedule thead').replaceChildren();$('#schedule tbody').replaceChildren();
    $('#loading').hidden = false; $('#table-wrap').hidden = true; $('#empty').hidden = true;
    $('#summary').textContent = '호실 확인 중';
    $('#status').textContent = '시간표를 불러오는 중입니다.';setMessage('');
    try {
      if (!validDate()) throw new Error('조회 날짜를 선택하세요.');
      const response = await fetcher(`/api/schedule?date=${encodeURIComponent(day)}`, {
        signal: controller.signal, cache: 'no-store', credentials: 'same-origin',
      });
      if (response.status === 401) {reauthenticate();return;}
      if (!response.ok) throw new Error(await responseError(response, '시간표 조회에 실패했습니다.'));
      const data = await response.json();
      if (ticket !== serial) return;
      if (data.date !== day || !Array.isArray(data.rooms)) throw new Error('조회 날짜와 응답이 일치하지 않습니다.');
      snapshot = data;
      const checked = new Intl.DateTimeFormat('ko-KR', {
        timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
      }).format(new Date(data.checked_at));
      $('#status').textContent = `${checked} 확인 · ${data.stale ? '이전 결과' : data.cached ? '최근 결과' : '새로 확인'}`;
      const unknown = data.rooms.filter(room => room.state !== 'ok').length;
      setMessage(data.stale ? `이전 조회 결과입니다. 현재 예약 가능 여부와 다를 수 있습니다. ${data.warning || ''}` :
        unknown ? `${unknown}개 호실은 확인 불가 상태이며 물음표로 표시됩니다.` : '');
      render();
    } catch (error) {
      if (ticket !== serial || error.name === 'AbortError') return;
      setMessage(error.message || '시간표를 불러올 수 없습니다. 새로고침이 필요합니다.');
      $('#status').textContent = '시간표를 불러올 수 없습니다.';
      $('#summary').textContent = '확인되지 않은 상태';
    } finally {
      if (ticket === serial) {$('#loading').hidden = true; $('#refresh').disabled = false;}
    }
  }
  $('#refresh').addEventListener('click', load);
  $('#date').addEventListener('change', load);
  $('#capacity').addEventListener('input', render);
  for (const button of doc.querySelectorAll('[data-group]')) {
    button.addEventListener('click', () => {
      group = button.dataset.group;
      for (const item of doc.querySelectorAll('[data-group]')) item.setAttribute('aria-pressed', String(item === button));
      render();
    });
  }
  const move = delta => {
    if (!validDate()) return;
    const date = new Date(`${$('#date').value}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + delta);
    $('#date').value = date.toISOString().slice(0,10);load();
  };
  $('#prev').addEventListener('click', () => move(-1));
  $('#next').addEventListener('click', () => move(1));
  $('#today').addEventListener('click', () => {$('#date').value = $('#date').min;load();});
  $('#logout').addEventListener('click', async () => {
    $('#logout').disabled=true;
    try {
      const response=await fetcher('/api/logout',{method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'X-Library-CSRF':configuration.csrf_token || ''}});
      if (response.status===401 || response.ok) {reauthenticate();return;}
      throw new Error(await responseError(response,'로그아웃을 완료할 수 없습니다.'));
    } catch (error) {setMessage(error.message || '로그아웃을 완료할 수 없습니다.');$('#logout').disabled=false;}
  });
  doc.defaultView?.addEventListener('pagehide', () => controller?.abort(), {once: true});
  dateButtons();
  // Exactly one initial load. No intervals, visibility refresh, focus refresh or prefetch.
  try {
    const response = await fetcher('/api/config', {cache: 'no-store',credentials:'same-origin'});
    if (response.status === 401) {reauthenticate();return;}
    if (!response.ok) throw new Error('조회 설정을 불러올 수 없습니다.');
    const config = await response.json();
    configuration = config;
    $('#account-label').textContent=typeof config.account_label==='string'?config.account_label:'';
    $('#date').min = config.today;$('#date').max = config.last_date;$('#date').value = config.today;
    await load();
  } catch (error) {
    $('#status').textContent = '연결 실패';setMessage(error.message);
  }
}

if (typeof document !== 'undefined') boot();
