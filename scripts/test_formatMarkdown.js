const fs = require('fs');

const esc = t => { if (!t) return ''; return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); };
const escAttr = t => String(t).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

const code = fs.readFileSync('C:/Users/Hetin/work/git/tea_agent/tea_agent/server/static/app.js', 'utf8');
const start = code.indexOf('function formatMarkdown');
const end = code.indexOf('\n}', start) + 2;
const fmCode = code.substring(start, end);

eval(fmCode);

const tests = [
  ['basic text', 'hello world', ['hello world']],
  ['markdown link', '[click](https://example.com)', ['<a', 'href="https://example.com"', 'md-link', '>click<']],
  ['bare URL', 'visit https://example.com/page', ['<a', 'md-autolink']],
  ['md link + bare URL', '[L](https://a.com) and https://b.com', ['md-link', 'md-autolink']],
  ['topic link', '#topic:abc12345-def0-7890-abcd-ef1234567890', ['md-topic-link', 'data-topic="abc12345']],
  ['download .zip via md link', '[f](f.zip)', ['📦']],
  ['download .pdf via md link', '[d](d.pdf)', ['📄']],
  ['download .exe via md link', '[s](s.exe)', ['⚙️']],
  ['download .zip via bare URL', 'https://x.com/f.zip', ['📦', 'md-autolink']],
  ['download .pdf via bare URL', 'https://x.com/d.pdf', ['📄', 'md-autolink']],
  ['download .7z', '[a](a.7z)', ['📦']],
  ['download .msi', '[a](a.msi)', ['⚙️']],
  ['download .dmg', '[a](a.dmg)', ['💿']],
  ['download .apk', '[a](a.apk)', ['📱']],
  ['download .tar.gz', '[a](a.tar.gz)', ['📦']],
  ['URL with params', 'http://test.com?a=1&b=2', ['md-autolink']],
  ['inline code protects URL', '`https://safe.com`', ['md-inline-code']],
  ['no double icon', 'https://x.com/f.zip', [function(r) { return (r.match(/📦/g) || []).length === 1; }]],
];

let passed = 0;
for (const [name, input, checks] of tests) {
  const result = formatMarkdown(input);
  const missing = checks.filter(c => {
    if (typeof c === 'function') return !c(result);
    return !result.includes(c);
  });
  if (missing.length === 0) {
    console.log('PASS:', name);
    passed++;
  } else {
    console.log('FAIL:', name, '- missing:', missing.join(', '));
    console.log('  out:', result.substring(0, 200));
  }
}
console.log('\nPassed:', passed, '/', tests.length);
