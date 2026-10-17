// "Check the request": the agent's reading of the request -> what Sottovoce needs, or what is missing.
// data = { video_url, language, age, title, needed_by, email, focus } from the agent's output structure.
const r = data || {};
const clean = (v, n) => String(v == null ? '' : v).replace(/["\\{}\r\n\t]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);
const url = clean(r.video_url, 600);
const language = clean(r.language, 5).toLowerCase();
const age = clean(r.age, 8).replace(/\s/g, '');
const levels = { '5-8': '-young', '8-13': '', '14-18': '-teen' };
const missing = [];
if (!/^https:\/\/[^\s]+$/i.test(url)) missing.push('video');
if (language !== 'en' && language !== 'it') missing.push('language');
if (!Object.prototype.hasOwnProperty.call(levels, age)) missing.push('age');
return {
  ready: missing.length === 0,
  missing: missing,
  video_url: url,
  language: language,
  age: age,
  audience: missing.length ? '' : language + levels[age],
  title: clean(r.title, 80) || 'Lesson',
  needed_by: clean(r.needed_by, 40),
  email: clean(r.email, 120),
  focus: clean(r.focus, 200),
};
