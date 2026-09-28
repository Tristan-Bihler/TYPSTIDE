import "./styles.css";

import { App } from "./app";

const root = document.querySelector<HTMLElement>("#app");
if (root) new App(root).start();
