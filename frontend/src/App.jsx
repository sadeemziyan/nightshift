import { useState } from 'react'
import network from './mock/network.json'

function App() {
  const [selectedSystemId, setSelectedSystemId] = useState(
    network.systems[0]?.id ?? ''
  )

  const selectedSystem = network.systems.find(
    (system) => system.id === selectedSystemId
  )

  return (
    <main className="min-h-screen bg-slate-950 p-8 text-slate-100">
      <p className="text-sm font-semibold uppercase tracking-widest text-cyan-400">
        Operations console
      </p>

      <h1 className="mt-2 text-4xl font-bold">Nightshift</h1>

      <p className="mt-3 text-slate-400">
        Detect problems. Compare plans. Dispatch crews.
      </p>

      <div className="mt-8">
        <label
          htmlFor="system"
          className="mb-2 block text-sm text-slate-400"
        >
          Select system
        </label>

        <select
          id="system"
          value={selectedSystemId}
          onChange={(event) => setSelectedSystemId(event.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-3"
        >
          {network.systems.map((system) => (
            <option key={system.id} value={system.id}>
              {system.id}
            </option>
          ))}
        </select>
      </div>

      {selectedSystem ? (
        <section className="mt-8">
          <h2 className="text-xl font-semibold">
            {selectedSystem.id} facilities
          </h2>

          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {selectedSystem.facilities.map((facility) => (
              <article
                key={facility.id}
                className="rounded-xl border border-slate-800 bg-slate-900 p-5"
              >
                <h3 className="font-semibold text-cyan-400">
                  {facility.id}
                </h3>

                <dl className="mt-4 space-y-2 text-sm">
                  <div>
                    <dt className="text-slate-400">Wells</dt>
                    <dd>{facility.wells.length}</dd>
                  </div>

                  <div>
                    <dt className="text-slate-400">Tank capacity</dt>
                    <dd>
                      {facility.tank.capacity_bbl.toLocaleString()}{' '}
                      {network.meta.units.volume}
                    </dd>
                  </div>

                  <div>
                    <dt className="text-slate-400">Pump</dt>
                    <dd>{facility.pump.id}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      ) : (
        <p className="mt-8 text-slate-400">No systems available.</p>
      )}
    </main>
  )
}

export default App