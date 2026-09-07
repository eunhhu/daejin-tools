export function kstNow(now = new Date()) {
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(now).map(part => [part.type, part.value]));
  return {date: `${values.year}-${values.month}-${values.day}`, time: `${values.hour}:${values.minute}`};
}

export function filterRooms(rooms, group, people) {
  return rooms.filter(room => (group === 'all' || room.group === group)
    && room.minimum <= people && room.capacity >= people);
}

export function cellState(room, time, day, now = kstNow()) {
  if (day < now.date || (day === now.date && time < now.time)) return 'elapsed';
  if (room.state !== 'ok') return 'unknown';
  return room.starts.includes(time) ? 'available' : 'unavailable';
}

export function timeAxis(rooms) {
  // Reference grid, not an assertion that the library is open at these times.
  const values = new Set();
  for (let minutes = 9 * 60; minutes <= 20 * 60; minutes += 30) {
    values.add(`${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`);
  }
  for (const room of rooms) for (const time of room.starts) values.add(time);
  return [...values].sort();
}

export function detailURL(room, day) {
  const [year, month, date] = day.split('-');
  const params = new URLSearchParams({sloc_code: 'DJUL', group_code: room.group,
    seminar_code: room.code, seminar_name: room.name, resv_datev: day,
    year, month, day: date, min_personnel: String(room.minimum), max_personnel: String(room.capacity)});
  return `https://library.daejin.ac.kr/seminar_resv.mir?${params}`;
}
