/** 产品/助手显示名唯一真源（消息头、欢迎语、流式气泡共用）。
 *
 *  不 import 的两处静态页需手工同步（无法参与打包模块图）：`index.html` 的
 *  `<title>`、`public/splash.html` 的 `<title>` 与 `.name`；外壳侧另有
 *  `src-tauri/tauri.conf.json` 的 productName / 两处窗口 title。 */
export const ASSISTANT_NAME = '灵燕智能'
