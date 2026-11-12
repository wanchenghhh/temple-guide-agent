import { toast } from "./static/js/core.js?v=__APP_VERSION__";
import { initHomeDirectory } from "./static/js/home_directory.js?v=__APP_VERSION__";
import { initThread, renderHero, userMessage, assistantMessage, scrollToBottom } from './static/js/thread.js?v=__APP_VERSION__';
import { initTempleWorkspace } from './static/js/temple_workspace.js?v=__APP_VERSION__';
import { initExperience, enterWorkspace } from './static/js/experience.js?v=__APP_VERSION__';
import { initComposer, prefillComposer } from './static/js/composer.js?v=__APP_VERSION__';

function previewMessage(text) {
  enterWorkspace();
  userMessage({ text, omitted: 0 });
  assistantMessage('这里是界面静态预览，暂未连接推荐服务。要体验真实对话，请按页面上方的运行说明启动项目。', { speak: false });
}

initThread();
initTempleWorkspace();
const emptyNote = document.querySelector("#templeWorkspace .workspace-empty p");
if (emptyNote) emptyNote.textContent = "这是静态界面预览；连接后端后，这里会展示真实候选与资料。";
initExperience({ onResume: () => requestAnimationFrame(() => scrollToBottom({ force: true, replyStart: true })) });
initComposer({ onSubmit: async ({ text }) => previewMessage(text) });
initHomeDirectory({ onPrompt: text => {
  if (prefillComposer(text)) document.getElementById("composer").requestSubmit();
  else toast("已保留输入框中的草稿，请先发送或清空后再选择。");
} });
renderHero({ onChip: previewMessage, onMemory: () => {} });
