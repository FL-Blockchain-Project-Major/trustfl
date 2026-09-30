import { fetchAPI } from '../../libs/api';

export default async function RoundsPage() {
  let federations: any[] = [];
  let rounds: any[] = [];
  let updates: any[] = [];
  let bctx: any[] = [];

  try {
    federations = await fetchAPI('/federations/');
    if (federations.length > 0) {
      const fedId = federations[0].id;
      rounds = await fetchAPI(`/rounds/federation/${fedId}`);
      
      for (const r of rounds) {
        const rUpdates = await fetchAPI(`/updates/round/${r.id}`);
        updates.push(...rUpdates);
      }

      bctx = await fetchAPI('/blockchain/transactions');
    }
  } catch (err) {}

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Rounds</h2>
      <div className="bg-white rounded shadow overflow-hidden overflow-x-auto">
        <table className="min-w-full text-left whitespace-nowrap">
          <thead className="bg-gray-100 text-gray-600 text-sm">
            <tr>
              <th className="px-6 py-3 font-medium">Round ID</th>
              <th className="px-6 py-3 font-medium">Participating Clients</th>
              <th className="px-6 py-3 font-medium">Aggregation Status</th>
              <th className="px-6 py-3 font-medium">Model Version</th>
              <th className="px-6 py-3 font-medium">Transaction Info</th>
            </tr>
          </thead>
          <tbody className="divide-y text-sm">
            {rounds.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-4 text-center text-gray-500">No rounds found.</td>
              </tr>
            ) : (
              rounds.map((r) => {
                const roundUpdates = updates.filter(u => u.round_id === r.id);
                const participatingClients = new Set(roundUpdates.map(u => u.client_id)).size;
                const roundTx = bctx.find(tx => tx.entity_id === r.id);
                
                return (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 font-mono">{r.id}</td>
                    <td className="px-6 py-4">{participatingClients}</td>
                    <td className="px-6 py-4">
                      <span className="px-2 py-1 rounded-full text-xs bg-blue-100 text-blue-700">
                        {r.status}
                      </span>
                    </td>
                    <td className="px-6 py-4">{r.model_version || 'Initial'}</td>
                    <td className="px-6 py-4">
                      {roundTx ? (
                        <div className="flex flex-col">
                          <span className="text-xs text-gray-500">Hash: {roundTx.tx_hash ? `${roundTx.tx_hash.substring(0, 10)}...` : 'Pending'}</span>
                          <span className={`text-xs ${roundTx.status === 'CONFIRMED' ? 'text-green-600' : 'text-yellow-600'}`}>Status: {roundTx.status}</span>
                        </div>
                      ) : (
                        <span className="text-gray-400">None</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
