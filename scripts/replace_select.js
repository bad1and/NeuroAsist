const fs = require('fs');
const path = require('path');

const files = [
  'apps/web/src/App.tsx',
  'apps/web/src/coding.tsx',
  'apps/web/src/stt-capture.tsx',
  'apps/web/src/pages/settings.tsx'
];

for (const file of files) {
  const filePath = path.join(__dirname, '..', file);
  if (fs.existsSync(filePath)) {
    let content = fs.readFileSync(filePath, 'utf8');
    
    // Add import if not exists
    if (!content.includes('CustomSelect')) {
      const importPath = file.includes('pages') ? '../components/CustomSelect' : './components/CustomSelect';
      content = `import { CustomSelect } from "${importPath}";\n` + content;
    }

    // Replace <select and </select>
    content = content.replace(/<select/g, '<CustomSelect');
    content = content.replace(/<\/select>/g, '</CustomSelect>');
    
    fs.writeFileSync(filePath, content);
    console.log(`Updated ${file}`);
  } else {
    console.log(`File not found: ${file}`);
  }
}
