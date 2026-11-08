window.MathJax = {
  loader: {
    paths: { mathjax: '/static/vendor/mathjax-3.2.2/es5' }
  },
  tex: {
    inlineMath: [['\\(', '\\)'], ['$','$']],
    displayMath: [['\\[', '\\]'], ['$$','$$']]
  },
  svg: {
    // 导出 PDF 时 html2canvas 对 <use> 字形缓存容易出现公式重影。
    // 直接输出独立路径，显示效果不变，但截图/导出更稳定。
    fontCache: 'none'
  }
};
