const fs = require('fs');
let content = fs.readFileSync('state.tsx', 'utf8');
content = content.replace("replace(',', ',')", "replace(',', ' в')");
fs.writeFileSync('state.tsx', content, 'utf8');
