import { fetchAPI } from '../../libs/api';

export default async function ModelsPage() {
  let federations: any[] = [];
  let artifacts: any[] = [];
  try {
    federations = await fetchAPI('/federations/');
    if (federations.length > 0) {
      artifacts = await fetchAPI(`/artifacts/federation/${federations[0].id}`);
    }
  } catch (err) {}

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Model Artifacts</h2>
      <div className="bg-white rounded shadow overflow-hidden overflow-x-auto">
        <table className="min-w-full text-left whitespace-nowrap">
          <thead className="bg-gray-100 text-gray-600 text-sm">
            <tr>
              <th className="px-6 py-3 font-medium">Model Version</th>
              <th className="px-6 py-3 font-medium">SHA-256</th>
              <th className="px-6 py-3 font-medium">CID / URI</th>
              <th className="px-6 py-3 font-medium">Evaluation Metrics</th>
            </tr>
          </thead>
          <tbody className="divide-y text-sm">
            {artifacts.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-6 py-4 text-center text-gray-500">No model artifacts found.</td>
              </tr>
            ) : (
              artifacts.map((a) => (
                <tr key={a.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">{a.model_version || 'N/A'}</td>
                  <td className="px-6 py-4 font-mono text-xs">{a.sha256_hash}</td>
                  <td className="px-6 py-4 font-mono text-xs">{a.uri}</td>
                  <td className="px-6 py-4 text-gray-400 italic">Not evaluated</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
