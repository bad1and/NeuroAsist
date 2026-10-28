// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
const mock=vi.hoisted(()=>({handler:null as null|((event:{payload:any})=>Promise<void>),invoke:vi.fn().mockResolvedValue(undefined)}));
vi.mock("./desktop",()=>({isDesktopApp:()=>true}));
vi.mock("@tauri-apps/api/core",()=>({invoke:mock.invoke}));
vi.mock("@tauri-apps/api/event",()=>({listen:vi.fn(async (_name:string,handler:any)=>{mock.handler=handler;return ()=>{};})}));
import { useDesktopConversationBridge, type DesktopConversationSnapshot } from "./desktop-avatar-bridge";
const snapshot:DesktopConversationSnapshot={session_id:"current",ready:true,loading:false,document_busy:false,microphone_active:false,microphone_starting:false,sound_muted:false,voice_state:"idle",cue:"",error:null};
afterEach(()=>{cleanup();mock.invoke.mockClear();});
it("deduplicates commands and rejects a stale session without sending it",async()=>{
  const execute=vi.fn().mockResolvedValue(undefined);
  renderHook(()=>useDesktopConversationBridge(snapshot,execute));
  const command={id:"one",type:"send",session_id:"current",text:"Привет"};
  await act(async()=>{await mock.handler?.({payload:command});await mock.handler?.({payload:command});
    await mock.handler?.({payload:{...command,id:"old",session_id:"old"}});});
  expect(execute).toHaveBeenCalledTimes(1);
  expect(mock.invoke).toHaveBeenCalledWith("desktop_avatar_snapshot",{snapshot:expect.objectContaining({ack:"old",command_error:expect.stringContaining("Диалог изменился")})});
});
