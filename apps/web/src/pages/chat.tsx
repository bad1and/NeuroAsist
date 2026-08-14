// Chat remains implemented next to the shell for now, but is fetched only
// when the user opens the conversation route. Keeping this bridge separate
// lets the shell split the route without duplicating its large voice graph.
export { ChatPage as default } from "../App";
