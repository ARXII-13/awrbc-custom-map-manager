# Deserialize a BinaryFormatter stream with the REAL .NET Framework formatter,
# substituting a permissive placeholder for every game type. This exercises the
# same code path the game does, so type-materialisation errors surface here.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.Serialization;

[Serializable]
public class Any : ISerializable
{
    public Any() { }
    protected Any(SerializationInfo info, StreamingContext ctx) { }
    public void GetObjectData(SerializationInfo info, StreamingContext ctx) { }
}

public class AnyBinder : SerializationBinder
{
    public override Type BindToType(string assemblyName, string typeName)
    {
        int rank = 0;
        string t = typeName;
        while (t.EndsWith("]"))
        {
            int open = t.LastIndexOf('[');
            if (open < 0) break;
            string dims = t.Substring(open + 1, t.Length - open - 2);
            rank = dims.Length + 1;          // "" -> 1, "," -> 2
            t = t.Substring(0, open);
            break;
        }
        if (rank == 1) return typeof(Any[]);
        if (rank == 2) return typeof(Any[,]);
        return typeof(Any);
    }
}
'@ -ErrorAction Stop

foreach ($path in $args) {
    $name = Split-Path $path -Leaf
    $bf = New-Object System.Runtime.Serialization.Formatters.Binary.BinaryFormatter
    $bf.Binder = New-Object AnyBinder
    $fs = [System.IO.File]::OpenRead($path)
    try {
        $o = $bf.Deserialize($fs)
        "{0,-26} OK    -> {1}" -f $name, $o.GetType().Name
    } catch {
        $ex = $_.Exception
        "{0,-26} FAIL  {1}" -f $name, $ex.GetType().Name
        "                           {0}" -f $ex.Message
        if ($ex.InnerException) {
            "                           inner: {0}: {1}" -f $ex.InnerException.GetType().Name, $ex.InnerException.Message
        }
    } finally {
        $fs.Close()
    }
}
