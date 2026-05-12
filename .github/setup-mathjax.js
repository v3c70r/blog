const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

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

themeConfig = themeConfig.replace(/katex:\n    enable: true/gi, 'katex:\n    enable: false');
themeConfig = themeConfig.replace(/related_posts:\n    enable: true/gi, 'related_posts:\n    enable: false');

fs.writeFileSync(themeConfigPath, themeConfig);
console.log('Updated theme config for MathJax and disabled katex/related_posts');

try {
  execSync('rm -rf node_modules/hexo-math', { stdio: 'ignore' });
  console.log('Removed hexo-math package');
} catch (e) {}

console.log('MathJax configuration complete!');