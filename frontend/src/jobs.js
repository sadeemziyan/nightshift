import { CATEGORY, fmtClock } from './status'

// Turn the recommended plan and the open inspections into one list of things a person has to go do.
export function buildJobs(plan, alerts, t) {
  const jobs = []
  for (const sys of plan?.systems ?? []) {
    const best = sys.plans.find((p) => p.rank === 1) ?? sys.plans[0]
    for (const f of best?.per_facility ?? []) {
      const trucks = Math.max(1, f.trucks)
      f.trip_arrivals.forEach((a, i) => {
        jobs.push({
          id: `truck:${f.event_id}:${a.arrives_unix}`,
          kind: 'truck',
          when: a.arrives_unix,
          urgency: 'high',
          title: `Truck ${(i % trucks) + 1} to ${f.facility_id}, trip ${Math.floor(i / trucks) + 1}: haul water to the disposal site`,
          detail: `Pick up ${Math.round(a.removes_bbl)} bbl and take it to the disposal site. Arrive ${fmtClock(a.arrives_unix)}Z.`,
          where: f.facility_id,
        })
      })
      for (const s of f.shut_in) {
        jobs.push({
          id: `shutin:${f.event_id}:${s.well}`,
          kind: 'shutin',
          when: t + s.start_min * 60,
          urgency: 'medium',
          title: `Shut in ${s.well}`,
          detail: `Close it ${s.start_min} min from now and keep it closed about ${Math.round(s.minutes)} min.`,
          where: f.facility_id,
        })
      }
    }
  }
  for (const a of alerts) {
    if (a.status !== 'ongoing' || a.recommended_actions?.[0]?.type !== 'field_inspection') continue
    jobs.push({
      id: `inspect:${a.event_id}`,
      kind: 'inspect',
      when: t,
      urgency: a.urgency,
      title: `Inspect ${a.asset_id}`,
      detail: `${CATEGORY[a.category] ?? a.category}. ${(a.reasons?.length ? a.reasons : a.evidence ?? [])[0] ?? ''}`,
      where: a.facility_id,
    })
  }
  return jobs.sort((x, y) => x.when - y.when)
}
