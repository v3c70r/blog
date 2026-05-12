const fs = require('fs');
const path = require('path');

console.log('Configuring MathJax...');

fs.mkdirSync('source/_data', { recursive: true });

const headContent = `<script>
  window.MathJax = {
    tex: {
      inlineMath: {'[+]': [['$', '$'], ['\\\\(', '\\\\)']]}
    },
    startup: {
      pageReady: () => MathJax.startup.defaultPageReady()
    }
  };
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" id="MathJax-script" async></script>
`;

fs.writeFileSync('source/_data/head.swig', headContent);
console.log('Created source/_data/head.swig');

const themeConfigPath = 'node_modules/hexo-theme-next/_config.yml';
let themeConfig = fs.readFileSync(themeConfigPath, 'utf8');

themeConfig = themeConfig.replace(/#head: source\/_data\/head.swig/gi, 'head: source/_data/head.swig');
themeConfig = themeConfig.replace(/enable: false/gi, 'enable: true');

fs.writeFileSync(themeConfigPath, themeConfig);
console.log('Updated theme config for MathJax');

console.log('MathJax configuration complete!');