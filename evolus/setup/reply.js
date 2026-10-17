// "Reply to the teacher": sources[0] = Check the request, sources[1] = Start the described lesson
// (Sottovoce's answer { id }, empty when the request was not ready and the lesson was not started).
const req = sources[0].data || {};
const job = sources[1] ? sources[1].data : null;
const it = req.language === 'it';
const ages = { '5-8': it ? '5-8 anni' : 'ages 5-8', '8-13': it ? '8-13 anni' : 'ages 8-13', '14-18': it ? '14-18 anni' : 'ages 14-18' };
if (job && job.id) {
  const link = 'https://sottovoce-ai.web.app/app/#' + job.id;
  const by = req.needed_by ? (it ? ' Ci serve per ' : ' Needed by ') + req.needed_by + '.' : '';
  return {
    status: 'started', job_id: job.id, link: link, audience: req.audience, title: req.title,
    email: req.email, needed_by: req.needed_by, focus: req.focus,
    reply: it
      ? 'Grazie. La lezione descritta "' + req.title + '" è in preparazione, in italiano, per ' + ages[req.age] + '.' + by + ' Si segue qui: ' + link + ' . Le frasi che il controllo non ha potuto verificare aspettano lì la sua revisione prima che un bambino le senta.'
      : 'Thank you. The described lesson "' + req.title + '" is being made, in English, for ' + ages[req.age] + '.' + by + ' Follow it here: ' + link + ' . Any line the checker could not verify waits there for your review before a child hears it.',
  };
}
const need = {
  video: it ? 'il link https al file video (fino a 5 minuti)' : 'an https link to the video file (up to 5 minutes)',
  language: it ? 'la lingua in cui il bambino ascolta (italiano o inglese)' : 'the language the child listens in (English or Italian)',
  age: it ? "l'età del bambino (5-8, 8-13 o 14-18)" : "the child's age (5-8, 8-13 or 14-18)",
};
const list = (req.missing || []).map(function (m) { return need[m]; }).join(it ? ' e ' : ', and ');
return {
  status: 'needs_info', missing: req.missing || [],
  reply: (it ? 'Per descrivere questa lezione mi serve ancora ' : 'To describe this lesson I still need ') + list + '.',
};
