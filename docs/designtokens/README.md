# Tender Agent Design Tokens · v1.2

**Source:** Ardot 画布文件 `720053744468339`
**更新时间:** 2026-08-29
**总计:** 48 个 token · 5 个集合 · Light + Dark 双 mode

| 集合 | 数量 | 模式 | 类型 |
|---|---|---|---|
| Color | 16 | Light + Dark | COLOR |
| Spacing | 8 | — | FLOAT |
| Radius | 4 | — | FLOAT |
| Typography | 15 (9 字号 + 4 字重 + 2 字体族) | — | FLOAT / STRING |
| Shadow | 5 | Light + Dark | STRING |

## v1.1 → v1.2 增量

| 新增 | 之前 | 现在 |
|---|---|---|
| **Dark mode** | 只有 Light | Color + Shadow 各加 Dark mode，token 名不变只换值 |
| **Shadow 提到变量** | 写在画布演示里 | 进 Shadow 集合（STRING，直接是 CSS box-shadow 值） |
| **复合 token Recipes** | 无 | 5 份组件配方（button-primary / secondary / input / status-tag / card），放在 tokens.css 里直接用 |
| **字体族变量** | 写在画布文本里 | `Typography-font-family-base` / `-mono` 进变量集 |

## 文件

| 文件 | 用途 |
|---|---|
| `tokens.json` | W3C DTCG（含 Light/Dark 双 mode） |
| `tokens.css` | CSS 变量 + 派生 + 5 份组件配方（直接抄） |
| `tokens.scss` | SCSS 变量 + mixin（含 Dark 备用值） |
| `README.md` | 本文件 |

## 暗色模式切换

```html
<!-- 显式切换 -->
<html data-theme="dark">

<!-- 跟随系统 + 用户偏好 -->
@media (prefers-color-scheme: dark) {
  :root { /* 把 Dark 值再写一遍，或用 [data-theme="dark"] selector */ }
}
```

token 名 **完全不变**——`var(--Color-bg-canvas)` 在两种模式下都有效，只是值不一样。组件代码零改动。

## 状态色派生配方

```css
/* 浅底不另存 token，用 color-mix() 现场派生 */
.bg-success-soft { background: color-mix(in srgb, var(--Color-success) 12%, var(--Color-bg-canvas)); }
.bg-warning-soft { background: color-mix(in srgb, var(--Color-warning) 12%, var(--Color-bg-canvas)); }
.bg-danger-soft  { background: color-mix(in srgb, var(--Color-danger)  12%, var(--Color-bg-canvas)); }
```

注意：color-mix 的第二个色用 `var(--Color-bg-canvas)` 而不是 hardcoded `white`，这样暗色模式下派生出来的也是暗色 tint。

## 组件配方（直接抄）

`tokens.css` 末尾有 5 份可用的类：

```css
.btn-primary    /* 主操作按钮 */
.btn-secondary  /* 次要按钮 */
.input          /* 输入框 */
.status          /* 状态 pill：灰底 + 彩色点 */
.status-success / .status-warning / .status-danger  /* dot 颜色 */
.card            /* 卡片 */
```

zcode 写组件时直接复用这些类，不要自己拼 token。

## 在 Figma 里用

ardot 不直连 Figma。路径：
1. Figma 装 Tokens Studio 插件（免费）
2. `Sync → Import → From file` 选 `tokens.json`
3. 插件会自动把 Light/Dark 两个 mode 都导入成 Figma Variables
4. 切换 mode：选中 Frame → 右侧面板 `Variable mode` 选 Light / Dark

## 在 Tailwind 里用

### v3
```js
import tokens from './design-tokens/tokens.json';
export default {
  theme: {
    colors: {
      primary:        tokens.Color['brand-primary'].Light,
      'primary-hover': tokens.Color['brand-primary-hover'].Light,
      'primary-soft':  tokens.Color['brand-primary-soft'].Light,
      success:        tokens.Color.success.Light,
      warning:        tokens.Color.warning.Light,
      danger:         tokens.Color.danger.Light,
      'text-primary':  tokens.Color['text-primary'].Light,
      'bg-subtle':     tokens.Color['bg-subtle'].Light,
      'border-default': tokens.Color['border-default'].Light,
    },
    extend: {
      spacing: Object.fromEntries(
        Object.entries(tokens.Spacing).map(([k, v]) => [k.replace('space-', ''), v.$value])
      ),
      borderRadius: Object.fromEntries(
        Object.entries(tokens.Radius).map(([k, v]) => [k.replace('radius-', ''), v.$value])
      ),
      fontFamily: {
        sans: 'var(--Typography-font-family-base)',
        mono: 'var(--Typography-font-family-mono)',
      },
      boxShadow: Object.fromEntries(
        Object.entries(tokens.Shadow).map(([k, v]) => [k.replace('shadow-', ''), v.Light])
      ),
    },
  },
};
```

### v4
```css
@import './design-tokens/tokens.css';
@import 'tailwindcss';
@theme inline {
  --color-primary: var(--Color-brand-primary);
  --color-primary-hover: var(--Color-brand-primary-hover);
  --color-primary-soft: var(--Color-brand-primary-soft);
  --color-success: var(--Color-success);
  --color-warning: var(--Color-warning);
  --color-danger: var(--Color-danger);
  --color-text-primary: var(--Color-text-primary);
  /* ... */
  --font-sans: var(--Typography-font-family-base);
  --font-mono: var(--Typography-font-family-mono);
  --shadow-sm: var(--Shadow-shadow-sm);
  --shadow-md: var(--Shadow-shadow-md);
}
```

## 设计原则

- **从 token 取，不硬编码**：所有色 / 尺寸 / 圆角都溯源到一个 token
- **找不到 token = 加 token**（或 color-mix 派生），不是改组件
- **离散值禁用**：间距必须是 2/4/8/12/16/24/32/48，圆角必须 4/8/12/9999
- **品牌主色只用一个色相**：Light 蓝 #2563EB，Dark 蓝 #3B82F6
- **状态色只存纯色**：tint 用 color-mix() 派生（且第二个色用 `var(--Color-bg-canvas)` 跟随模式）
- **状态 pill 用 dot 模式**：灰底 + 彩色点 + 深字（Linear 风格）
- **阴影用纯黑 + 高不透明度**（Dark 模式）：暗底上浅色阴影看不见
- **字体族**进变量：西文用打包的 Inter variable（SIL OFL，放 `public/fonts/`），中文走平台原生（macOS 苹方 / Windows 雅黑 / Linux Noto Sans SC）——Inter 无 CJK 自然穿透系统字体，与 OS 混排零割裂（2026-08-29 定稿，Sarasa 方案暂不采用）

## 下次迭代

- [ ] 复合 token 真正入变量：把 5 份 recipe 的 padding/radius/fontSize 命名成 `btn-primary-padding` 这种（目前只在 CSS 类里）
- [ ] 动画 token：duration-150/300/500 + easing
- [ ] 断点 token：breakpoint-sm/md/lg/xl
- [ ] z-index token：z-dropdown / z-modal / z-toast
