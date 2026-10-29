// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mock=vi.hoisted(() => ({
  listeners:new Map<string,(event:{payload:any})=>void>(), invoke:vi.fn(), overlay:vi.fn(), update:vi.fn(), failSend:false, snapshot:null as any,
}));
vi.mock("@tauri-apps/api/core",()=>({invoke:mock.invoke}));
vi.mock("@tauri-apps/api/event",()=>({listen:vi.fn(async (name:string,callback:(event:{payload:any})=>void)=>{
  mock.listeners.set(name,callback); return ()=>mock.listeners.delete(name);
})}));
vi.mock("../api",()=>({getAvatarOverlay:mock.overlay,updateAvatarOverlay:mock.update,WS_EVENTS_URL:"ws://test/events"}));
import { DesktopAvatar } from "./DesktopAvatar";
import { desktopAvatarControls, localAvatarRect, placePanel } from "../desktop-avatar";
const layout={monitor:"primary",x_ratio:0.8,y_ratio:1,height_dip:400};
const overlay={visible:true,always_on_top:true,locked:true,desktop_mode:"waist",layouts:{waist:layout},subtitles_enabled:true,subtitle_position:"above",scale:1,monitor:"primary",x:0,y:0,width:640,height:720};
const geometry={desktop_mode:"waist",monitor:{id:"primary",name:"Test",area:{x:0,y:0,width:1024,height:760},scale:1,primary:true},rect:{x:750,y:360,width:264,height:400},layout,transforming:false,commit:false};
const conversation={session_id:"session",ready:true,loading:false,document_busy:false,microphone_active:false,microphone_starting:false,sound_muted:false,voice_state:"speaking",cue:"Субтитры видны без наведения.",error:null};
function emit(name:string,payload:unknown) { mock.listeners.get(name)?.({payload}); }
function publishConversation(patch:Partial<typeof conversation>) {
  mock.snapshot={...mock.snapshot,...patch};
  emit("desktop-avatar-conversation",mock.snapshot);
}
beforeEach(()=>{
  mock.listeners.clear();mock.invoke.mockReset();mock.failSend=false;
  mock.snapshot={...conversation};
  mock.update.mockReset();
  mock.overlay.mockResolvedValue(overlay);mock.update.mockImplementation(async patch=>({...overlay,...patch}));
  vi.stubGlobal("WebSocket",class {close(){} });
  mock.invoke.mockImplementation(async (name,args)=>{
    if(name==="configure_desktop_avatar") return geometry;
    if(name==="desktop_avatar_command") queueMicrotask(()=>emit("desktop-avatar-conversation",{
      ...mock.snapshot,ack:args.command.id,command_error:args.command.type==="send" && mock.failSend?"Нет связи":undefined,
    }));
  });
});
afterEach(()=>{cleanup();vi.useRealTimers();document.body.classList.remove("desktop-avatar-body");vi.unstubAllGlobals();});

it("does not show a historical cue while Iris is idle",async()=>{
  mock.snapshot={...conversation,voice_state:"idle",cue:"Старая реплика."};
  render(<DesktopAvatar/>);
  await screen.findByLabelText("Переместить Iris");
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
  act(()=>publishConversation({cue:"Ответ ещё не произнесён.",loading:true}));
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
});

it("hides the last spoken cue exactly two seconds after speech despite idle snapshots",async()=>{
  render(<DesktopAvatar/>);
  await screen.findByRole("region",{name:"Субтитры Iris"});
  vi.useFakeTimers();
  act(()=>publishConversation({voice_state:"idle"}));
  act(()=>vi.advanceTimersByTime(1000));
  act(()=>publishConversation({cue:"Новая, но не произнесённая строка."}));
  act(()=>vi.advanceTimersByTime(999));
  expect(screen.getByRole("region",{name:"Субтитры Iris"})).toHaveTextContent(conversation.cue);
  act(()=>vi.advanceTimersByTime(1));
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
  act(()=>vi.advanceTimersByTime(3000));
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
});

it("cancels the old hide timer for resumed speech and clears the cue on session changes",async()=>{
  render(<DesktopAvatar/>);
  await screen.findByRole("region",{name:"Субтитры Iris"});
  vi.useFakeTimers();
  act(()=>publishConversation({voice_state:"idle"}));
  act(()=>vi.advanceTimersByTime(1000));
  act(()=>publishConversation({voice_state:"speaking",cue:"Следующая фраза."}));
  act(()=>vi.advanceTimersByTime(1500));
  expect(screen.getByRole("region",{name:"Субтитры Iris"})).toHaveTextContent("Следующая фраза.");
  act(()=>publishConversation({voice_state:"idle"}));
  act(()=>vi.advanceTimersByTime(2000));
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
  act(()=>publishConversation({voice_state:"speaking",cue:"Последняя фраза."}));
  act(()=>publishConversation({session_id:"another",voice_state:"idle",cue:"Старая строка другого диалога."}));
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
  act(()=>publishConversation({session_id:"session",voice_state:"idle"}));
  expect(screen.queryByRole("region",{name:"Субтитры Iris"})).not.toBeInTheDocument();
});

it("shows subtitles without hover and reveals the toolbar only over the avatar",async()=>{
  render(<DesktopAvatar/>);
  await screen.findByRole("region",{name:"Субтитры Iris"});
  expect(screen.getByRole("region",{name:"Субтитры Iris"}).querySelector(".confirmation-rim")).toBeNull();
  expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  act(()=>emit("desktop-avatar-hover",true));
  await waitFor(()=>expect(screen.getByRole("toolbar")).toBeVisible());
  expect(screen.queryByRole("button",{name:"Изменить размер Iris"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:/положение и размер|Открыть приложение Iris/})).not.toBeInTheDocument();
  expect(screen.getByRole("group",{name:"Микрофон и звук"})).toContainElement(screen.getByRole("button",{name:"Включить микрофон"}));
  // Only actual controls become native hit regions; the full-screen toolbar stays transparent.
  await waitFor(()=>expect(mock.invoke).toHaveBeenCalledWith("set_desktop_avatar_regions",expect.anything()));
  expect(mock.update).not.toHaveBeenCalled();
});
it("keeps resize available when placement is unlocked in settings",async()=>{
  mock.overlay.mockResolvedValue({...overlay,locked:false});
  render(<DesktopAvatar/>); await screen.findByLabelText("Переместить Iris");
  act(()=>emit("desktop-avatar-hover",true));
  expect(await screen.findByRole("button",{name:"Изменить размер Iris"})).toBeVisible();
});
it.each([true,false])("keeps controls usable across native avatar gaps and buttons (locked=%s)",async locked=>{
  mock.overlay.mockResolvedValue({...overlay,locked});
  render(<DesktopAvatar/>);
  await screen.findByRole("region",{name:"Субтитры Iris"});
  vi.useFakeTimers();
  act(()=>emit("desktop-avatar-hover",true));
  const avatar=screen.getByLabelText("Переместить Iris");
  const toolbar=screen.getByRole("toolbar");
  // Crossing Unity/WebView or click-through gaps can send DOM leave without
  // leaving the shared native hover area. The native value stays true.
  fireEvent.pointerEnter(avatar);
  fireEvent.pointerLeave(avatar);
  act(()=>vi.advanceTimersByTime(700));
  expect(toolbar).toBeVisible();
  const microphone=screen.getByRole("button",{name:"Включить микрофон"});
  fireEvent.pointerEnter(microphone);
  fireEvent.click(microphone);
  fireEvent.pointerLeave(toolbar);
  fireEvent.blur(window);
  act(()=>vi.advanceTimersByTime(700));
  expect(toolbar).toBeVisible();
  const sound=screen.getByRole("button",{name:"Выключить звук Iris"});
  fireEvent.pointerEnter(sound);
  fireEvent.click(sound);
  await act(async()=>{});
  for(const type of ["microphone","sound"]) {
    expect(mock.invoke).toHaveBeenCalledWith("desktop_avatar_command",{command:expect.objectContaining({type,session_id:"session"})});
  }
});
it("hides controls after leaving the native area and cancels hiding on reentry",async()=>{
  render(<DesktopAvatar/>);
  await screen.findByLabelText("Переместить Iris");
  vi.useFakeTimers();
  act(()=>emit("desktop-avatar-hover",true));
  act(()=>emit("desktop-avatar-hover",false));
  act(()=>vi.advanceTimersByTime(349));
  expect(screen.getByRole("toolbar")).toBeVisible();
  act(()=>emit("desktop-avatar-hover",true));
  act(()=>vi.advanceTimersByTime(700));
  expect(screen.getByRole("toolbar")).toBeVisible();
  act(()=>emit("desktop-avatar-hover",false));
  act(()=>vi.advanceTimersByTime(350));
  expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
  act(()=>emit("desktop-avatar-hover",true));
  expect(screen.getByRole("toolbar")).toBeVisible();
});
it("switches left panels, retains the draft and returns focus on Escape",async()=>{
  render(<DesktopAvatar/>); await screen.findByLabelText("Переместить Iris");
  act(()=>emit("desktop-avatar-hover",true));
  const chat=screen.getByRole("button",{name:"Написать Iris"});
  const tools=screen.getByRole("button",{name:"Инструменты"});
  fireEvent.click(chat);
  const input=screen.getByRole("textbox",{name:"Сообщение Iris"});
  expect(input).toHaveFocus();
  fireEvent.change(input,{target:{value:"Черновик"}});
  expect(chat).toHaveAttribute("aria-expanded","true");
  expect(chat).toHaveClass("dp-accent");
  fireEvent.click(tools);
  expect(screen.getByRole("dialog",{name:"Инструменты Iris"})).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(chat).toHaveAttribute("aria-expanded","false");
  fireEvent.keyDown(screen.getByRole("dialog"),{key:"Escape"});
  expect(tools).toHaveFocus();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(chat);
  expect(screen.getByRole("textbox",{name:"Сообщение Iris"})).toHaveValue("Черновик");
  fireEvent.click(chat);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("sends to the existing session, preserves failed text and clears accepted text",async()=>{
  render(<DesktopAvatar/>); await screen.findByLabelText("Переместить Iris");
  await waitFor(()=>expect(mock.invoke).toHaveBeenCalledWith("desktop_avatar_command",expect.anything()));
  act(()=>emit("desktop-avatar-hover",true));
  fireEvent.click(screen.getByRole("button",{name:"Написать Iris"}));
  const input=screen.getByRole("textbox",{name:"Сообщение Iris"});
  fireEvent.change(input,{target:{value:"Привет"}});mock.failSend=true;
  fireEvent.click(screen.getByRole("button",{name:"Отправить сообщение"}));
  await screen.findByText("Нет связи");expect(input).toHaveValue("Привет");
  mock.failSend=false;
  fireEvent.click(screen.getByRole("button",{name:"Отправить сообщение"}));
  await waitFor(()=>expect(input).toHaveValue(""));
  const sends=mock.invoke.mock.calls.filter(([name,args])=>name==="desktop_avatar_command"&&args.command.type==="send");
  expect(sends).toHaveLength(2);expect(sends[0][1].command.session_id).toBe("session");
});
it("saves the completed gesture only for its own desktop mode",async()=>{
  render(<DesktopAvatar/>);await screen.findByLabelText("Переместить Iris");
  const moved={...geometry,layout:{...layout,x_ratio:0.2}};
  act(()=>emit("desktop-avatar-geometry",moved));expect(mock.update).not.toHaveBeenCalled();
  act(()=>emit("desktop-avatar-geometry",{...moved,commit:true}));
  await waitFor(()=>expect(mock.update).toHaveBeenCalledWith({layouts:{waist:moved.layout}}));
});
it("converts negative physical coordinates into local DIPs and keeps the panel on screen",()=>{
  const local=localAvatarRect({...geometry,monitor:{...geometry.monitor,area:{x:-1920,y:0,width:1920,height:1040},scale:2},rect:{x:-1500,y:240,width:600,height:800}} as any);
  expect(local).toEqual({x:210,y:120,width:300,height:400});
  const panel=placePanel({x:800,y:500,width:200,height:200},296,220,{x:0,y:0,width:1024,height:760});
  expect(panel.x+panel.width).toBeLessThanOrEqual(1012);expect(panel.y+panel.height).toBeLessThanOrEqual(748);
});
it("anchors controls inside the avatar and opens panels to their left without resizing it",()=>{
  const avatar={x:600,y:200,width:352,height:400};
  const work={x:0,y:0,width:1024,height:760};
  const controls=desktopAvatarControls(avatar,work);
  expect(controls.left.x).toBe(608);
  expect(controls.right.x+controls.right.width).toBe(944);
  const panel=placePanel(avatar,296,220,work);
  expect(panel.x+panel.width).toBe(controls.left.x-12);
  expect(panel.y).toBe(controls.left.y);
  const edge={...avatar,x:0,width:93};
  const edgeControls=desktopAvatarControls(edge,work);
  const edgePanel=placePanel(edge,296,220,work);
  expect(edgePanel.x).toBe(12);
  expect(edgePanel.y).toBeGreaterThanOrEqual(edgeControls.left.y+edgeControls.left.height);
  expect(edgeControls.left.x+44).toBeLessThanOrEqual(edgeControls.right.x);
});
