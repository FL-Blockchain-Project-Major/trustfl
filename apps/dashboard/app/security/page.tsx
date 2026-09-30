import { fetchAPI } from '../../libs/api';

export default async function SecurityPage() {
  let federations: any[] = [];
  let updates: any[] = [];
  let proofs: any[] = [];
  let bctx: any[] = [];

  try {
    federations = await fetchAPI('/federations/');
    if (federations.length > 0) {
      const fedId = federations[0].id;
      const rounds = await fetchAPI(`/rounds/federation/${fedId}`);
      for (const r of rounds) {
        const rUpdates = await fetchAPI(`/updates/round/${r.id}`);
        updates.push(...rUpdates);
      }
      for (const u of updates) {
        const uProofs = await fetchAPI(`/proofs/update/${u.id}`);
        proofs.push(...uProofs);
      }
      bctx = await fetchAPI('/blockchain/transactions');
    }
  } catch (err) {}

  const verifiedUpdates = updates.filter(u => u.status === 'VERIFIED' || u.status === 'AGGREGATED').length;
  const rejectedUpdates = updates.filter(u => u.status === 'REJECTED').length;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Security Overview</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white p-4 rounded shadow border-l-4 border-green-500">
          <h3 className="text-gray-500 text-sm">Verified Updates</h3>
          <p className="text-lg font-semibold">{verifiedUpdates}</p>
        </div>
        <div className="bg-white p-4 rounded shadow border-l-4 border-red-500">
          <h3 className="text-gray-500 text-sm">Rejected Updates</h3>
          <p className="text-lg font-semibold">{rejectedUpdates}</p>
        </div>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded shadow p-6 overflow-x-auto">
          <h3 className="text-xl font-semibold mb-4 border-b pb-2">Proof Verification</h3>
          <table className="min-w-full text-left whitespace-nowrap text-sm">
            <thead>
              <tr>
                <th className="px-2 py-2 text-gray-500">Update ID</th>
                <th className="px-2 py-2 text-gray-500">Protocol</th>
                <th className="px-2 py-2 text-gray-500">Validity</th>
              </tr>
            </thead>
            <tbody>
              {proofs.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-2 py-2 text-center text-gray-500">No proofs found.</td>
                </tr>
              ) : (
                proofs.map((p) => (
                  <tr key={p.id} className="border-t">
                    <td className="px-2 py-2 font-mono truncate max-w-[150px]">{p.update_id}</td>
                    <td className="px-2 py-2">{p.protocol}</td>
                    <td className="px-2 py-2">
                      <span className={`px-2 py-1 rounded-full text-xs ${p.is_valid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                        {p.is_valid ? 'Valid' : 'Invalid'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        
        <div className="bg-white rounded shadow p-6 overflow-x-auto">
          <h3 className="text-xl font-semibold mb-4 border-b pb-2">Blockchain Transactions</h3>
          <table className="min-w-full text-left whitespace-nowrap text-sm">
            <thead>
              <tr>
                <th className="px-2 py-2 text-gray-500">Contract</th>
                <th className="px-2 py-2 text-gray-500">Function</th>
                <th className="px-2 py-2 text-gray-500">Status</th>
                <th className="px-2 py-2 text-gray-500">Tx Hash</th>
              </tr>
            </thead>
            <tbody>
              {bctx.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-2 py-2 text-center text-gray-500">No transactions found.</td>
                </tr>
              ) : (
                bctx.map((tx) => (
                  <tr key={tx.id} className="border-t">
                    <td className="px-2 py-2">{tx.contract_name}</td>
                    <td className="px-2 py-2">{tx.function_name}</td>
                    <td className="px-2 py-2">
                      <span className={`px-2 py-1 rounded-full text-xs ${tx.status === 'CONFIRMED' ? 'bg-green-100 text-green-700' : tx.status === 'FAILED' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'}`}>
                        {tx.status}
                      </span>
                    </td>
                    <td className="px-2 py-2 font-mono truncate max-w-[150px]">{tx.tx_hash || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
