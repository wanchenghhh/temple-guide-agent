import { initThread, renderHero, userMessage, assistantMessage, scrollToBottom } from './static/js/thread.js?v=pages-353e373';
import { initTempleWorkspace } from './static/js/temple_workspace.js?v=pages-353e373';
import { initExperience, enterWorkspace } from './static/js/experience.js?v=pages-353e373';
import { initComposer } from './static/js/composer.js?v=pages-353e373';

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
renderHero({ onChip: previewMessage, onMemory: () => {} });
