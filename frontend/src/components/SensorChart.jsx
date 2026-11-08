import { useBaseline } from '../hooks'
import { BandChart } from './BaselineCharts'

// Pump behavior chart used in the facility detail view.
function SensorChart({ assetId, metric = 'flow_bpd', t, hours = 6, usingMock }) {
  const result = useBaseline(assetId, metric, t, hours, usingMock)
  if (!result) return <div className="skeleton h-72" aria-label="Loading chart" />
  return <BandChart result={result} />
}

export default SensorChart
