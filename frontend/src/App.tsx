import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ComponentsGallery } from "./dev/Components";
import { Launch } from "./views/Launch";
import { History, LiveRun, Report } from "./views/stubs";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Launch />} />
        <Route path="/runs/:id" element={<LiveRun />} />
        <Route path="/reports/:id" element={<Report />} />
        <Route path="/history" element={<History />} />
        <Route path="/dev/components" element={<ComponentsGallery />} />
      </Routes>
    </BrowserRouter>
  );
}
