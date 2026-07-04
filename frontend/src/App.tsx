import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ComponentsGallery } from "./dev/Components";
import { akamaiReport } from "./fixtures/akamaiReport";
import { Launch } from "./views/Launch";
import { ReportView } from "./views/report/ReportView";
import { History, LiveRun } from "./views/stubs";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Launch />} />
        <Route path="/runs/:id" element={<LiveRun />} />
        <Route path="/reports/:id" element={<ReportView />} />
        <Route path="/history" element={<History />} />
        <Route path="/dev/components" element={<ComponentsGallery />} />
        <Route path="/dev/report" element={<ReportView report={akamaiReport} />} />
      </Routes>
    </BrowserRouter>
  );
}
