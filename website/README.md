# 灵燕智能官网（静态单页）

纯 HTML + CSS + 少量原生 JS，无构建链。视觉语言参考 Steep：暖白底 + 衬线大标题
（Noto Serif SC，weight 400）+ 近黑白灰 + 单一桃色强调 + 浮动产品碎片拼贴 +
24px 圆角卡片 + 9999px 胶囊按钮。主题层集中在 `assets/style.css` 顶部的 `:root` tokens。

## 字体

大标题用 **Noto Serif CJK SC Regular** 的自托管子集
（`assets/fonts/display-serif.woff2`，只含标题用字，中英字形同源——混排基线才齐，
**不要换成纯拉丁衬线**）。改了 h1/h2/h3 文案后重新生成：

```bash
# 一次性下载源字体（约 25MB，SIL OFL）
curl -L -o /tmp/NotoSerifSC-Regular.otf \
  "https://github.com/notofonts/noto-cjk/raw/main/Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Regular.otf"
python3 tools/make_font_subset.py /tmp/NotoSerifSC-Regular.otf
```

需要 `fonttools` + `brotli`（`pip3 install fonttools brotli`）。

## 本地预览

```bash
python3 -m http.server 4173 -d website
# 打开 http://localhost:4173
```

（或直接双击 `index.html`，衬线标题会回落到系统宋体。）

## 上线（GitHub Pages）

仓库 Settings → Pages → Source 选 **GitHub Actions**，配一个最简单的
static sites 工作流，`source` 指向 `website/` 目录即可。之后域名解析到
`<user>.github.io/<repo>/` 或绑定自定义域名。

注意：站内链接全部是相对路径，挂在子路径（如 `/Bid_Copilot_client/`）下也能正常工作。

## 结构

```
website/
  index.html          # 整页：导航 / Hero(含纯 CSS 应用示意图) / 数字带 / 五步流程 / 核心能力三段图文行 / FAQ(左题右列) / CTA(燕子水印) / 页脚
  assets/style.css    # 全部样式；:root 主题 tokens 在顶部
  assets/main.js      # 吸顶导航阴影 + 移动端菜单 + IntersectionObserver 进场动画
  assets/logo.svg     # 燕子 logo（fill=currentColor，颜色随 CSS）
  assets/favicon.svg  # 站点图标
```

## 待定项（上线前要拍板）

- 正式域名（当前下载按钮指向 `github.com/joychin/Bid_Copilot_client/releases/latest`）
- 页脚免责声明措辞（当前：辅助撰写、不承诺中标结果、责任由提交者自负）
- 「常见问题」里 Windows/macOS 之外的系统支持口径
