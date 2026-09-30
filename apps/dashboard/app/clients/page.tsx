import { fetchAPI } from '../../libs/api';

export default async function ClientsPage() {
  let federations: any[] = [];
  let clients: any[] = [];
  let updates: any[] = [];
  let proofs: any[] = [];

  try {
    federations = await fetchAPI('/federations/');
    if (federations.length > 0) {
      const fedId = federations[0].id;
      clients = await fetchAPI(`/clients/federation/${fedId}`);
      
      const rounds = await fetchAPI(`/rounds/federation/${fedId}`);
      for (const r of rounds) {
        const rUpdates = await fetchAPI(`/updates/round/${r.id}`);
        updates.push(...rUpdates);
      }
      
      for (const u of updates) {
        const uProofs = await fetchAPI(`/proofs/update/${u.id}`);
        proofs.push(...uProofs);
      }
    }
  } catch (err) {}

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Clients</h2>
      <div className="bg-white rounded shadow overflow-hidden overflow-x-auto">
        <table className="min-w-full text-left whitespace-nowrap">
          <thead className="bg-gray-100 text-gray-600 text-sm">
            <tr>
              <th className="px-6 py-3 font-medium">ID</th>
              <th className="px-6 py-3 font-medium">Status</th>
              <th className="px-6 py-3 font-medium">Last Participation</th>
              <th className="px-6 py-3 font-medium">Samples</th>
              <th className="px-6 py-3 font-medium">Local Metrics (Loss)</th>
              <th className="px-6 py-3 font-medium">Signature / Proof</th>
            </tr>
          </thead>
          <tbody className="divide-y text-sm">
            {clients.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-4 text-center text-gray-500">No clients found.</td>
              </tr>
            ) : (
              clients.map((c) => {
                const clientUpdates = updates.filter(u => u.client_id === c.id).sort((a,b) => new Date(b.submitted_at).getTime() - new Date(a.submitted_at).getTime());
                const latestUpdate = clientUpdates[0];
                let proofState = 'N/A';
                if (latestUpdate) {
                  const clientProofs = proofs.filter(p => p.update_id === latestUpdate.id);
                  const validProof = clientProofs.find(p => p.is_valid);
                  proofState = validProof ? 'Verified' : (clientProofs.length > 0 ? 'Invalid' : 'Pending');
                }

                return (
                  <tr key={c.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 font-mono">{c.id}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs ${c.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                        {c.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4">{latestUpdate ? new Date(latestUpdate.submitted_at).toLocaleString() : 'Never'}</td>
                    <td className="px-6 py-4">{latestUpdate?.num_examples || '-'}</td>
                    <td className="px-6 py-4">{latestUpdate?.loss ? latestUpdate.loss.toFixed(4) : '-'}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs ${proofState === 'Verified' ? 'bg-green-100 text-green-700' : proofState === 'Invalid' ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-700'}`}>
                        {proofState}
                      </span>
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
