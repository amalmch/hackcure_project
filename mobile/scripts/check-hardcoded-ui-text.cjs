const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const roots = ['app', 'src'];
const textProps = new Set([
  'title', 'message', 'description', 'label', 'placeholder', 'confirmText', 'cancelText',
  'accessibilityLabel', 'accessibilityHint', 'tabBarLabel', 'headerTitle', 'alertTitle',
]);
const languageNeutral = new Set(['HackCure', 'Dr.', '• Dr.', 'min', 'min)', 'km', 'mL / day', 'kcal / day', 'mL / jour', 'kcal / jour', 'cm •', 'kg', '&quot;']);
const files = [];

function collect(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) collect(filename);
    else if (/\.(tsx|ts)$/.test(entry.name) && !filename.includes(`${path.sep}i18n${path.sep}`)) files.push(filename);
  }
}

roots.forEach((root) => collect(path.join(__dirname, '..', root)));
const findings = [];
const translationReferences = [];
const hasUserText = (value) => /[A-Za-zÀ-ÿ]{2,}/u.test(value.trim());

for (const filename of files) {
  const sourceText = fs.readFileSync(filename, 'utf8');
  const source = ts.createSourceFile(filename, sourceText, ts.ScriptTarget.Latest, true, filename.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);

  function report(node, value, kind) {
    if (hasUserText(value) && !languageNeutral.has(value.trim())) {
      const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
      findings.push(`${path.relative(path.join(__dirname, '..'), filename)}:${line + 1}: ${kind}: ${value.trim()}`);
    }
  }

  function visit(node) {
    if (ts.isCallExpression(node) && node.arguments.length && ts.isStringLiteral(node.arguments[0])) {
      const key = node.arguments[0].text;
      if (/^(common|auth|onboarding|home|treatment|medications|sport|nutrition|pharmacy|doctor|messages|appointments|medicalRecords|notifications|profile|companion|copy|validation|labels)\./.test(key)) {
        translationReferences.push({ filename, key });
      }
    }
    if (ts.isJsxText(node)) report(node, node.text, 'JSX text');
    if (ts.isJsxAttribute(node) && textProps.has(node.name.getText(source)) && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) report(node.initializer, node.initializer.text, node.name.getText(source));
      if (ts.isJsxExpression(node.initializer) && node.initializer.expression && ts.isStringLiteral(node.initializer.expression)) {
        report(node.initializer.expression, node.initializer.expression.text, node.name.getText(source));
      }
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
      && ['alert', 'prompt'].includes(node.expression.name.text)
      && ts.isIdentifier(node.expression.expression) && node.expression.expression.text === 'Alert') {
      node.arguments.slice(0, 2).forEach((argument) => {
        if (ts.isStringLiteral(argument)) report(argument, argument.text, 'Alert text');
      });
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}

const frenchLocale = fs.readFileSync(path.join(__dirname, '..', 'src', 'i18n', 'locales', 'fr.ts'), 'utf8');
for (const reference of translationReferences) {
  const key = reference.key.split('.').at(-1);
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (!new RegExp(`\\b${escapedKey}(?:_(?:one|other|zero|few|many))?\\s*:`).test(frenchLocale)) {
    findings.push(`${path.relative(path.join(__dirname, '..'), reference.filename)}: missing French translation key: ${reference.key}`);
  }
}

if (findings.length) {
  console.error(`Found ${findings.length} hardcoded user-facing string(s):\n${findings.join('\n')}`);
  process.exitCode = 1;
} else {
  console.log(`No hardcoded user-facing strings found in ${files.length} app/src TypeScript files.`);
}
