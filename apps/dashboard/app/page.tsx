import { fetchAPI } from '../libs/api';

export default async function Dashboard() {
  let federations: any[] = [];
  let clients: any[] = [];
  let rounds: any[] = [];
  let updates: any[] = [];
  let bctx: any[] = [];

  try {
    federations = await fetchAPI('/federations/');
    if (federations.length > 0) {
      const fedId = federations[0].id;
      clients = await fetchAPI(`/clients/federation/${fedId}`);
      rounds = await fetchAPI(`/rounds/federation/${fedId}`);
      
      // Fetch updates and txs for all rounds
      for (const r of rounds) {
        const rUpdates = await fetchAPI(`/updates/round/${r.id}`);
        updates.push(...rUpdates);
      }
      
      bctx = await fetchAPI('/blockchain/transactions');
    }
  } catch (err) {
    console.error(err);
  }

  const activeFed = federations[0];
  const activeRound = rounds.find(r => r.status === 'ACTIVE') || rounds[rounds.length - 1];
  const successfulUpdates = updates.filter(u => u.status === 'VERIFIED' || u.status === 'AGGREGATED').length;
  const failedUpdates = updates.filter(u => u.status === 'REJECTED').length;
  const txConfirmed = bctx.filter(tx => tx.status === 'CONFIRMED').length;
  const txTotal = bctx.length;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">System Overview</h2>
      
      {!activeFed ? (
        <div className="bg-white p-6 rounded shadow text-center">
          <p className="text-gray-500">No active federations found. System is waiting for initialization.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div className="bg-white p-4 rounded shadow border-l-4 border-blue-500">
            <h3 className="text-gray-500 text-sm">Federation Status</h3>
            <p className="text-lg font-semibold">{activeFed.status}</p>
            <p className="text-sm text-gray-400">ID: {activeFed.id}</p>
          </div>
          
          <div className="bg-white p-4 rounded shadow border-l-4 border-green-500">
            <h3 className="text-gray-500 text-sm">Current Round</h3>
            <p className="text-lg font-semibold">{activeRound ? `Round ${activeRound.round_number}` : 'None'}</p>
            <p className="text-sm text-gray-400">Status: {activeRound?.status || 'N/A'}</p>
          </div>

          <div className="bg-white p-4 rounded shadow border-l-4 border-indigo-500">
            <h3 className="text-gray-500 text-sm">Client Count</h3>
            <p className="text-lg font-semibold">{clients.length}</p>
            <p className="text-sm text-gray-400">Active participants</p>
          </div>

          <div className="bg-white p-4 rounded shadow border-l-4 border-emerald-500">
            <h3 className="text-gray-500 text-sm">Successful Updates</h3>
            <p className="text-lg font-semibold">{successfulUpdates}</p>
            <p className="text-sm text-gray-400">Verified or Aggregated</p>
          </div>

          <div className="bg-white p-4 rounded shadow border-l-4 border-red-500">
            <h3 className="text-gray-500 text-sm">Failed Updates</h3>
            <p className="text-lg font-semibold">{failedUpdates}</p>
            <p className="text-sm text-gray-400">Rejected contributions</p>
          </div>

          <div className="bg-white p-4 rounded shadow border-l-4 border-purple-500">
            <h3 className="text-gray-500 text-sm">Blockchain Status</h3>
            <p className="text-lg font-semibold">{txConfirmed} / {txTotal} Confirmed</p>
            <p className="text-sm text-gray-400">Ledger synchronization</p>
          </div>
        </div>
      )}
    </div>
  );
}
