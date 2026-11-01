import { BrowserRouter, Route, Routes } from "react-router-dom";

import { ComponentsGallery } from "./dev/Components";
import { akamaiReport, investigatedReport } from "./fixtures/akamaiReport";
import { History } from "./views/History";
import { Launch } from "./views/Launch";
import { LiveRun } from "./views/LiveRun";
import { ReportView } from "./views/report/ReportView";

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
        <Route path="/dev/report-investigated" element={<ReportView report={investigatedReport} />} />
      </Routes>
    </BrowserRouter>
  );
}
