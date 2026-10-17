// The output check of "Lesson request": only values the desk script knows, or empty.
if (['', 'en', 'it'].indexOf(data.language) < 0) return 'language must be en, it or empty';
if (['', '5-8', '8-13', '14-18'].indexOf(data.age) < 0) return 'age must be 5-8, 8-13, 14-18 or empty';
if (data.video_url && input.indexOf(data.video_url) < 0) return 'video_url must be copied exactly from the request';
return true;
