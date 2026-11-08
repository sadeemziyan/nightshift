import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

function NetworkMap({ system, state }) {
  const nodes = []
  const edges = []

  function addNode(id, label, x, y) {
    
    const tank = state?.tanks?.find((item) => item.id === id)
    const pump = state?.pumps?.find((item) => item.id === id)

    let color = '#64748b'
    let statusLabel = 'No reading'

    if (tank) {
    statusLabel = tank.state
    color = {
        normal: '#34d399',
        warning: '#fbbf24',
        shutdown: '#f87171',
    }[tank.state] ?? '#64748b'
    }

    if (pump) {
    statusLabel = {
        0: 'Stopped',
        1: 'Running',
        2: 'Fault',
    }[pump.status] ?? 'Unknown'

    color = {
        0: '#94a3b8',
        1: '#34d399',
        2: '#f87171',
    }[pump.status] ?? '#64748b'
    }

    nodes.push({
      id,
      position: { x, y },
      data: { label: `${label} — ${statusLabel}` },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        background: '#0f172a',
        color: '#e2e8f0',
        border: `2px solid ${color}`,
        borderRadius: 10,
        width: 180,
        padding: 12,
      },
    })
  }

  function connect(source, target) {
    edges.push({
      id: `${source}->${target}`,
      source,
      target,
      type: 'smoothstep',
      style: { stroke: '#22d3ee', strokeWidth: 2 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#22d3ee',
      },
    })
  }

  // Give each facility enough vertical room for its wells.
  let nextY = 0
  const facilityCenters = []

  system.facilities.forEach((facility) => {
    const rowHeight = Math.max(facility.wells.length, 1) * 100
    const centerY = nextY + (rowHeight - 100) / 2

    facilityCenters.push(centerY)

    facility.wells.forEach((well, index) => {
      addNode(well.id, `Well: ${well.id}`, 0, nextY + index * 100)
      connect(well.id, facility.tank.id)
    })

    addNode(
      facility.tank.id,
      `Tank: ${facility.tank.id}`,
      260,
      centerY
    )

    addNode(
      facility.pump.id,
      `Pump: ${facility.pump.id}`,
      520,
      centerY
    )

    addNode(
      facility.pipeline.id,
      `Pipeline: ${facility.pipeline.id}`,
      780,
      centerY
    )

    connect(facility.tank.id, facility.pump.id)
    connect(facility.pump.id, facility.pipeline.id)
    connect(facility.pipeline.id, system.disposal_site.id)

    nextY += rowHeight + 100
  })

  const disposalY = facilityCenters.length
    ? (facilityCenters[0] + facilityCenters[facilityCenters.length - 1]) / 2
    : 0

  addNode(
    system.disposal_site.id,
    `Disposal: ${system.disposal_site.id}`,
    1040,
    disposalY
  )

  return (
    <div className="mt-6 h-[600px] overflow-hidden rounded-xl border border-slate-800">
      <ReactFlow
        key={system.id}
        nodes={nodes}
        edges={edges}
        fitView
        minZoom={0.1}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        colorMode="dark"
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

export default NetworkMap
